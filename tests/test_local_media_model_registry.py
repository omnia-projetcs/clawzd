import json
from pathlib import Path

from app.tools.image_utils import _IMAGE_STYLE_MODELS
from app.tools_audio import QWEN_TTS_REPO, SFX_MODELS, _qwen_language, _qwen_speaker
from app.tools_image import _VIDEO_MODELS


ROOT = Path(__file__).resolve().parents[1]

REQUESTED_MODEL_IDS = {
    "forkjoin-ai/qwen3-tts-12hz-1.7b-customvoice",
    "OpenMOSS-Team/MOSS-SoundEffect-v2.0",
    "stabilityai/stable-audio-open-small",
    "stabilityai/stable-audio-3-small-sfx",
    "Lightricks/LTX-2.3-22b-LoRA-Foley-V2A",
    "nvidia/Qwen-Image-Flash",
    "krea/Krea-2-Turbo",
    "mage-flow-community/Mage-Flow",
    "PrunaAI/PrunaVAED",
    "zai-org/CogVideoX-2b",
    "Alissonerdx/LTX-Best-Face-ID",
    "aidealab/AnimeGen-T2V",
    "Wan-AI/Wan2.1-T2V-14B",
    "tencent/HunyuanVideo",
}


def test_requested_models_are_in_catalog():
    catalog = json.loads((ROOT / "models_catalog.json").read_text(encoding="utf-8"))
    assert REQUESTED_MODEL_IDS <= {item["id"] for item in catalog}


def test_new_image_models_have_runtime_adapters():
    assert _IMAGE_STYLE_MODELS["qwen_image_flash"]["pipeline"] == "qwen_image"
    assert _IMAGE_STYLE_MODELS["krea_2_turbo"]["pipeline"] == "krea2"
    assert _IMAGE_STYLE_MODELS["mage_flow"]["pipeline"] == "mage_flow"


def test_new_audio_models_have_runtime_adapters():
    assert QWEN_TTS_REPO in REQUESTED_MODEL_IDS
    assert {cfg["repo"] for cfg in SFX_MODELS.values()} == {
        "OpenMOSS-Team/MOSS-SoundEffect-v2.0",
        "stabilityai/stable-audio-open-small",
        "stabilityai/stable-audio-3-small-sfx",
        "Lightricks/LTX-2.3-22b-LoRA-Foley-V2A",
    }
    assert _qwen_language("fr") == "French"
    assert _qwen_speaker("fr-FR-HenriNeural") == "Aiden"


def test_new_video_models_have_composed_runtime_configs():
    assert _VIDEO_MODELS["cogvideox_2b"]["repo"] == "zai-org/CogVideoX-2b"
    assert _VIDEO_MODELS["prunavaed"]["vae_repo"] == "PrunaAI/PrunaVAED"
    assert _VIDEO_MODELS["ltx_face_id"]["adapter_repo"] == "Alissonerdx/LTX-Best-Face-ID"
    assert _VIDEO_MODELS["animegen_t2v"]["source_repo"] == "aidealab/AnimeGen-T2V"
    assert _VIDEO_MODELS["wan21_14b"]["source_repo"] == "Wan-AI/Wan2.1-T2V-14B"
    assert _VIDEO_MODELS["hunyuanvideo"]["source_repo"] == "tencent/HunyuanVideo"


def test_new_models_are_selectable_in_media_studio():
    template = (ROOT / "templates/partials/media_studio.html").read_text(encoding="utf-8")
    javascript = (ROOT / "static/js/studios/media.js").read_text(encoding="utf-8")
    for key in (
        "qwen_image_flash", "krea_2_turbo", "mage_flow", "prunavaed",
        "cogvideox_2b", "ltx_face_id", "animegen_t2v", "wan21_14b",
        "hunyuanvideo", "moss_soundeffect_v2", "stable_audio_open_small",
        "stable_audio_3_small_sfx", "ltx_23_foley",
    ):
        assert f'value="{key}"' in template
    assert "data-submode=\"sfx\"" in template
    assert "audio_model: audioModel" in javascript
