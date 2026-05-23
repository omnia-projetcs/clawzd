"""
Clawzd — WebSocket Voice RTVI-lite Router.
Provides sub-second, full-duplex conversational voice mode.
"""
import os
import re
import uuid
import logging
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from config import OLLAMA_MODEL, LLM_PROVIDER
from app.core.llm_provider import get_llm_provider
from app.tools_audio import _generate_tts_edge, _save_audio

logger = logging.getLogger("clawzd.voice_rtvi")
router = APIRouter(prefix="/voice/rtvi", tags=["Voice RTVI"])

# Keep track of active generation tasks per session
_active_sessions = {}

def split_sentences(text: str) -> list[str]:
    """Helper to split accumulated stream text into clean spoken sentences."""
    # Split on standard punctuation followed by space
    sentences = re.split(r'(?<=[.!?:;])\s+', text)
    return [s.strip() for s in sentences if s.strip()]

@router.websocket("/session")
async def websocket_voice_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = f"voice_{uuid.uuid4().hex[:8]}"
    logger.info("Voice RTVI WebSocket connected: %s", session_id)
    
    await websocket.send_json({"type": "connected", "session_id": session_id})

    # Default settings
    voice_style = "female_soft"
    language = "auto"
    
    # Store session task controller
    _active_sessions[session_id] = {
        "llm_task": None,
        "tts_queue": asyncio.Queue(),
        "interrupt": False,
        "running": True
    }
    
    session_state = _active_sessions[session_id]

    async def run_llm_and_tts(user_text: str):
        """Asynchronously stream from LLM, split sentences, synthesize, and stream audio chunks."""
        session_state["interrupt"] = False
        try:
            # 1. Update UI state
            await websocket.send_json({"type": "state", "state": "thinking"})
            
            # 2. Setup system prompt
            from app.core.preprompts import PREPROMPTS
            # Use voice pilot system prompt or a highly optimized fast voice persona
            system_prompt = (
                "You are Clawzd, a ultra-concise voice-pilot AI assistant. "
                "The user is talking to you hands-free in real-time. "
                "IMPORTANT RULES:\n"
                "1. Keep answers extremely short, warm, and natural (1 to 2 short sentences max, under 30 words).\n"
                "2. Speak directly to the point. Avoid long explanations, lists, or markdown formats.\n"
                "3. Write phonetically if needed, do not output technical code blocks or JSON unless asked.\n"
                "4. Answer in the language of the user."
            )
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"/no_think\n{user_text}"}  # /no_think for fast response
            ]
            
            # 3. Stream from active LLM provider
            provider = get_llm_provider()
            logger.info("Voice LLM calling provider: %s, model: %s", LLM_PROVIDER, OLLAMA_MODEL)
            
            accumulated_text = ""
            sent_sentences = []
            
            # Stream tokens
            async for chunk in provider.chat_stream(messages, model=OLLAMA_MODEL):
                if session_state["interrupt"]:
                    logger.info("Voice LLM stream interrupted!")
                    break
                
                accumulated_text += chunk
                
                # Check if we have complete sentences
                all_sentences = split_sentences(accumulated_text)
                
                # If we have more sentences than already sent, process the new complete ones
                if len(all_sentences) > 1:
                    for s in all_sentences[:-1]:
                        if s not in sent_sentences:
                            sent_sentences.append(s)
                            # Spawn background TTS task immediately for sub-second latency!
                            asyncio.create_task(synthesize_and_stream(s))
                            
                    # Retain the last incomplete sentence fragment
                    accumulated_text = all_sentences[-1]

            # Process any remaining text at the end of LLM generation
            final_text = accumulated_text.strip()
            if final_text and final_text not in sent_sentences and not session_state["interrupt"]:
                asyncio.create_task(synthesize_and_stream(final_text))
                
            await websocket.send_json({"type": "state", "state": "idle"})

        except asyncio.CancelledError:
            logger.info("Voice LLM stream cancelled via task cancel.")
        except Exception as e:
            logger.error("Error in Voice LLM/TTS pipeline: %s", e)
            await websocket.send_json({"type": "error", "message": str(e)})
            await websocket.send_json({"type": "state", "state": "idle"})

    async def synthesize_and_stream(sentence: str):
        """Synthesize a single sentence and send it immediately over websocket."""
        if session_state["interrupt"]:
            return
        
        # Clean clean tags, reasoning remnants, etc.
        sentence = re.sub(r'<[^>]*>', '', sentence).strip()
        if not sentence:
            return
            
        try:
            logger.info("Voice RTVI: synthesizing chunk: '%s'", sentence)
            await websocket.send_json({"type": "state", "state": "speaking"})
            
            # Call Edge TTS neural synthesiser
            audio_array, sr = await _generate_tts_edge(
                text=sentence,
                voice_style=voice_style,
                language=language,
                duration_max=60
            )
            
            if session_state["interrupt"]:
                return
                
            # Save the synthesized chunk
            filename = _save_audio(
                audio_array=audio_array,
                sample_rate=sr,
                format_type="mp3",
                prompt=f"[RTVI] {sentence}",
                mode="tts"
            )
            
            url = f"/data/audio/{filename}"
            
            # Stream the chunk details to the client to play back
            await websocket.send_json({
                "type": "audio_chunk",
                "url": url,
                "text": sentence
            })
            
        except Exception as e:
            logger.error("TTS Synthesizer failed for chunk '%s': %s", sentence, e)

    try:
        while True:
            # Receive text control message
            data = await websocket.receive_json()
            msg_type = data.get("type", "message")
            
            if msg_type == "config":
                voice_style = data.get("voice_style", voice_style)
                language = data.get("language", language)
                logger.info("Session config updated: voice=%s, lang=%s", voice_style, language)
                await websocket.send_json({"type": "configured", "status": "ok"})
                continue
                
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue
                
            if msg_type == "interrupt":
                logger.info("User interruption requested!")
                session_state["interrupt"] = True
                if session_state["llm_task"]:
                    session_state["llm_task"].cancel()
                    session_state["llm_task"] = None
                await websocket.send_json({"type": "cancelled"})
                await websocket.send_json({"type": "state", "state": "idle"})
                continue
                
            if msg_type == "transcript":
                user_text = data.get("text", "").strip()
                if not user_text:
                    continue
                    
                logger.info("Received real-time voice transcript: '%s'", user_text)
                
                # 1. Trigger interrupt on any active generation first
                session_state["interrupt"] = True
                if session_state["llm_task"]:
                    session_state["llm_task"].cancel()
                    
                # 2. Reset and start new conversational turn
                session_state["interrupt"] = False
                session_state["llm_task"] = asyncio.create_task(run_llm_and_tts(user_text))
                
    except WebSocketDisconnect:
        logger.info("Voice RTVI WebSocket disconnected: %s", session_id)
    except Exception as e:
        logger.error("Voice RTVI connection error: %s", e)
    finally:
        # Cleanup
        if session_id in _active_sessions:
            state = _active_sessions.pop(session_id)
            if state["llm_task"]:
                state["llm_task"].cancel()
