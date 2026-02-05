"""Model download and management."""

import os
from pathlib import Path


def get_cache_dir() -> Path:
    """Get the cache directory for model files (XDG compliant)."""
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        cache_dir = Path(xdg_cache) / "blurcam"
    else:
        cache_dir = Path.home() / ".cache" / "blurcam"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_model_path(force_download: bool = False) -> str:
    """
    Download model from HuggingFace Hub if not cached.
    Returns the local path to the model file.
    """
    from huggingface_hub import hf_hub_download

    cache_dir = get_cache_dir()
    model_file = cache_dir / "model.onnx"

    if model_file.exists() and not force_download:
        return str(model_file)

    print("Downloading selfie segmentation model from HuggingFace Hub...")
    print(f"This only happens once. Model will be cached at: {cache_dir}")
    print()

    downloaded_path = hf_hub_download(
        repo_id="onnx-community/mediapipe_selfie_segmentation",
        filename="onnx/model.onnx",
        local_dir=cache_dir,
        local_dir_use_symlinks=False,
    )

    return downloaded_path
