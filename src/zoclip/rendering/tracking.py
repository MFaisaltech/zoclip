"""Bounded sampled face focus. No identity recognition or audio/face association."""

import json
import sys


def smooth(samples: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result = []
    focus = 0.5
    for second, value in samples:
        # Bounded pan speed plus low-pass smoothing suppress jump cuts between faces.
        focus += max(-0.12, min(0.12, (value - focus) * 0.35))
        result.append((second, max(0.0, min(1.0, focus))))
    return result


def main() -> None:
    import cv2

    cv2.setNumThreads(1)
    source, start, duration = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    cascade = cv2.data.haarcascades  # type: ignore[attr-defined]
    detector = cv2.CascadeClassifier(cascade + "haarcascade_frontalface_default.xml")
    capture = cv2.VideoCapture(source, cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
    capture.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
    samples = []
    found = 0
    previous = 0.5
    try:
        for i in range(min(24, max(1, int(duration / 2) + 1))):
            second = min(duration - 0.001, i * max(2, duration / 24))
            capture.set(cv2.CAP_PROP_POS_MSEC, (start + second) * 1000)
            okay, frame = capture.read()
            if not okay:
                continue
            height, width = frame.shape[:2]
            scale = 320 / max(width, height)
            small = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))))
            sample_width = small.shape[1]
            faces = detector.detectMultiScale(
                cv2.cvtColor(small, cv2.COLOR_BGR2GRAY),
                scaleFactor=1.15,
                minNeighbors=5,
                minSize=(20, 20),
            )
            if len(faces):
                # Prefer a large face near prior focus. Diarization does not identify its location.
                face = max(
                    faces,
                    key=lambda f: (
                        (f[2] * f[3]) / (1 + abs((f[0] + f[2] / 2) / sample_width - previous))
                    ),
                )
                previous = (float(face[0]) + float(face[2]) / 2) / sample_width
                found += 1
            samples.append((second, previous if len(faces) else 0.5))
    finally:
        capture.release()
    print(
        json.dumps(
            {
                "mode": "sampled_face" if found else "center_fallback",
                "samples": smooth(samples) if found else [],
                "faces_found": found,
            }
        )
    )


if __name__ == "__main__":
    main()
