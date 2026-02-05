"""ONNX-based selfie segmentation for ARM64 Linux."""

import cv2
import numpy as np
import onnxruntime as ort


class SelfieSegmentation:
    """Selfie segmentation using ONNX Runtime (works on ARM64)."""

    def __init__(self, model_path: str):
        """Initialize ONNX Runtime session."""
        # Suppress warnings on ARM64
        sess_options = ort.SessionOptions()
        sess_options.log_severity_level = 3

        self.session = ort.InferenceSession(
            model_path,
            sess_options,
            providers=["CPUExecutionProvider"],
        )

        # Get model input/output info
        self.input_name = self.session.get_inputs()[0].name
        self.input_shape = self.session.get_inputs()[0].shape
        self.output_name = self.session.get_outputs()[0].name

        # Model expects NCHW format: (batch, channels, height, width)
        self.input_height = (
            self.input_shape[2] if isinstance(self.input_shape[2], int) else 256
        )
        self.input_width = (
            self.input_shape[3] if isinstance(self.input_shape[3], int) else 256
        )

    def preprocess(self, frame: np.ndarray) -> np.ndarray:
        """Preprocess frame for the model."""
        # Resize to model input size
        resized = cv2.resize(frame, (self.input_width, self.input_height))
        # Convert BGR to RGB
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        # Normalize to [0, 1]
        normalized = rgb.astype(np.float32) / 255.0
        # Transpose from HWC to CHW format: (H, W, C) -> (C, H, W)
        transposed = np.transpose(normalized, (2, 0, 1))
        # Add batch dimension: (1, C, H, W)
        batched = np.expand_dims(transposed, axis=0)
        return batched

    def predict(self, frame: np.ndarray) -> np.ndarray:
        """Run inference and return segmentation mask."""
        input_data = self.preprocess(frame)
        outputs = self.session.run([self.output_name], {self.input_name: input_data})
        mask = outputs[0][0]  # Remove batch dimension -> (1, H, W)

        # Handle NCHW output format: (1, H, W) -> (H, W)
        if len(mask.shape) == 3:
            mask = mask[0]

        return mask

    def get_mask(self, frame: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        """Get binary mask resized to original frame size."""
        mask = self.predict(frame)

        # Resize mask to original frame size
        h, w = frame.shape[:2]
        mask_resized = cv2.resize(mask, (w, h))

        # Apply threshold for binary mask
        binary_mask = (mask_resized > threshold).astype(np.float32)

        # Smooth the mask edges
        binary_mask = cv2.GaussianBlur(binary_mask, (7, 7), 0)

        return binary_mask


def apply_background_blur(
    frame: np.ndarray, mask: np.ndarray, blur_strength: int = 21
) -> np.ndarray:
    """Apply blur to background while keeping foreground sharp."""
    # Ensure blur_strength is odd
    if blur_strength % 2 == 0:
        blur_strength += 1

    # Create blurred version of the frame
    blurred = cv2.GaussianBlur(frame, (blur_strength, blur_strength), 0)

    # Expand mask to 3 channels
    mask_3ch = np.stack([mask] * 3, axis=-1)

    # Blend: foreground (mask=1) stays sharp, background (mask=0) gets blurred
    result = (frame * mask_3ch + blurred * (1 - mask_3ch)).astype(np.uint8)

    return result
