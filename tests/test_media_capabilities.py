from app import tools_image


def test_media_capabilities_openai_ready(monkeypatch):
    monkeypatch.setattr(tools_image, "ENABLE_CLOUD_MODELS", True)
    monkeypatch.setattr(tools_image, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(tools_image, "HUGGINGFACE_API_KEY", "")
    monkeypatch.setattr(tools_image, "OPENAI_IMAGE_MODEL", "gpt-image-test")
    monkeypatch.setattr(tools_image, "OPENAI_VIDEO_MODEL", "sora-test")
    monkeypatch.setattr(tools_image, "OPENAI_TTS_MODEL", "tts-test")
    monkeypatch.setattr(tools_image, "_check_gpu", lambda: True)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    caps = tools_image._build_media_capabilities()

    assert caps["status"] == "ok"
    assert caps["providers"]["openai"]["configured"] is True
    assert caps["modes"]["image"]["cloud"]["available"] is True
    assert caps["modes"]["image"]["cloud"]["model"] == "gpt-image-test"
    assert caps["modes"]["video"]["cloud"]["available"] is True
    assert caps["modes"]["video"]["cloud"]["model"] == "sora-test"
    assert caps["modes"]["audio"]["cloud"]["model"] == "tts-test"
    assert caps["modes"]["image"]["recommended_backend"] == "api"


def test_media_capabilities_missing_cloud_and_gpu(monkeypatch):
    monkeypatch.setattr(tools_image, "ENABLE_CLOUD_MODELS", True)
    monkeypatch.setattr(tools_image, "OPENAI_API_KEY", "")
    monkeypatch.setattr(tools_image, "HUGGINGFACE_API_KEY", "")
    monkeypatch.setattr(tools_image, "_check_gpu", lambda: False)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    caps = tools_image._build_media_capabilities()

    assert caps["status"] == "degraded"
    assert caps["local"]["gpu_available"] is False
    assert caps["modes"]["image"]["cloud"]["available"] is False
    assert "OPENAI_API_KEY or HUGGINGFACE_API_KEY" in caps["modes"]["image"]["cloud"]["reason"]
    assert caps["modes"]["video"]["cloud"]["available"] is False
    assert "OPENAI_API_KEY" in caps["modes"]["video"]["cloud"]["reason"]
