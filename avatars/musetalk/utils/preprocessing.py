from __future__ import annotations

from avatars.musetalk.utils.face_detection import (
    FaceAlignment as DetectorFaceAlignment,
    LandmarksType as DetectorLandmarksType,
)
import numpy as np
import cv2
import pickle
import torch
from tqdm import tqdm

try:
    import face_alignment as fan
except ImportError:  # Kept optional so the detector fallback still works.
    fan = None


device = "cuda" if torch.cuda.is_available() else "cpu"
_fan_model = None
_face_detector = None

# maker if the bbox is not sufficient 
coord_placeholder = (0.0,0.0,0.0,0.0)

def _get_fan_model():
    """Load the 68-point FAN model only while preparing an avatar."""
    global _fan_model
    if fan is None:
        raise RuntimeError(
            "MuseTalk landmark backend 'fan' requires face-alignment. "
            "Run scripts\\setup_musetalk_windows.ps1 or install "
            "face-alignment==1.5.0 in .venv."
        )
    if _fan_model is None:
        kwargs = {
            "flip_input": False,
            "device": device,
            "face_detector": "sfd",
        }
        # face-alignment 1.5 enables torch.compile by default. Compilation adds
        # a large one-off startup cost and is unnecessary for avatar creation.
        try:
            _fan_model = fan.FaceAlignment(
                fan.LandmarksType.TWO_D, compile=False, **kwargs
            )
        except TypeError:  # Compatibility with face-alignment 1.4.x.
            _fan_model = fan.FaceAlignment(fan.LandmarksType.TWO_D, **kwargs)
    return _fan_model


def _get_face_detector():
    """Load LiveTalking's S3FD detector for the compatibility fallback."""
    global _face_detector
    if _face_detector is None:
        _face_detector = DetectorFaceAlignment(
            DetectorLandmarksType._2D, flip_input=False, device=device
        )
    return _face_detector


def _bbox_from_landmarks(face_landmarks, frame_shape, upperbondrange=0):
    """Build the square-ish MuseTalk crop from native 68-point landmarks.

    This is the same geometry used by upstream MuseTalk: point 29 anchors the
    vertical centre and the chin distance is mirrored above it.  A raw face
    detector box includes too much forehead/background and distorts the mouth
    when it is resized to MuseTalk's 256x256 latent input.
    """
    landmarks = np.asarray(face_landmarks, dtype=np.float32)
    if landmarks.ndim != 2 or landmarks.shape[0] < 68 or landmarks.shape[1] < 2:
        return coord_placeholder

    height, width = frame_shape[:2]
    half_face_y = float(landmarks[29, 1]) + int(upperbondrange)
    max_y = float(np.max(landmarks[:, 1]))
    half_face_dist = max_y - half_face_y

    x1 = int(np.floor(np.min(landmarks[:, 0])))
    y1 = int(np.floor(half_face_y - half_face_dist))
    x2 = int(np.ceil(np.max(landmarks[:, 0])))
    y2 = int(np.ceil(max_y))

    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(x1 + 1, min(width, x2))
    y2 = max(y1 + 1, min(height, y2))
    return (x1, y1, x2, y2)

def read_imgs(img_list):
    frames = []
    print('reading images...')
    for img_path in tqdm(img_list):
        frame = cv2.imread(img_path)
        frames.append(frame)
    return frames

# def get_bbox_range(img_list,upperbondrange =0):
#     frames = read_imgs(img_list)
#     batch_size_fa = 1
#     batches = [frames[i:i + batch_size_fa] for i in range(0, len(frames), batch_size_fa)]
#     coords_list = []
#     landmarks = []
#     if upperbondrange != 0:
#         print('get key_landmark and face bounding boxes with the bbox_shift:',upperbondrange)
#     else:
#         print('get key_landmark and face bounding boxes with the default value')
#     average_range_minus = []
#     average_range_plus = []
#     for fb in tqdm(batches):
#         results = inference_topdown(model, np.asarray(fb)[0])
#         results = merge_data_samples(results)
#         keypoints = results.pred_instances.keypoints
#         face_land_mark= keypoints[0][23:91]
#         face_land_mark = face_land_mark.astype(np.int32)
        
#         # get bounding boxes by face detetion
#         bbox = fa.get_detections_for_batch(np.asarray(fb))
        
#         # adjust the bounding box refer to landmark
#         # Add the bounding box to a tuple and append it to the coordinates list
#         for j, f in enumerate(bbox):
#             if f is None: # no face in the image
#                 coords_list += [coord_placeholder]
#                 continue
            
#             half_face_coord =  face_land_mark[29]#np.mean([face_land_mark[28], face_land_mark[29]], axis=0)
#             range_minus = (face_land_mark[30]- face_land_mark[29])[1]
#             range_plus = (face_land_mark[29]- face_land_mark[28])[1]
#             average_range_minus.append(range_minus)
#             average_range_plus.append(range_plus)
#             if upperbondrange != 0:
#                 half_face_coord[1] = upperbondrange+half_face_coord[1] #手动调整  + 向下（偏29）  - 向上（偏28）

#     text_range=f"Total frame:「{len(frames)}」 Manually adjust range : [ -{int(sum(average_range_minus) / len(average_range_minus))}~{int(sum(average_range_plus) / len(average_range_plus))} ] , the current value: {upperbondrange}"
#     return text_range
    

def get_landmark_and_bbox(img_list, upperbondrange=0, backend="fan"):
    """Detect MuseTalk crops with FAN landmarks or the legacy detector box."""
    if backend not in {"fan", "detector"}:
        raise ValueError("landmark backend must be 'fan' or 'detector'")

    frames = read_imgs(img_list)
    coords_list = []
    print(
        f"extract face crops with backend={backend}; "
        f"bbox_shift={upperbondrange}"
    )

    if backend == "fan":
        landmark_model = _get_fan_model()
        for frame in tqdm(frames):
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            predictions = landmark_model.get_landmarks_from_image(rgb_frame)
            if not predictions:
                coords_list.append(coord_placeholder)
                continue
            # The presenter should be the dominant face if another face slips
            # into the source frame.
            face_landmarks = max(
                predictions,
                key=lambda points: np.ptp(points[:, 0]) * np.ptp(points[:, 1]),
            )
            coords_list.append(
                _bbox_from_landmarks(
                    face_landmarks, frame.shape, upperbondrange=upperbondrange
                )
            )
    else:
        detector = _get_face_detector()
        for frame in tqdm(frames):
            detections = detector.get_detections_for_batch(
                np.expand_dims(frame, axis=0)
            )
            detected = detections[0]
            if detected is None:
                coords_list.append(coord_placeholder)
                continue

            x1, y1, x2, y2 = map(int, detected)
            y1 = max(0, min(y2 - 1, y1 + int(upperbondrange)))
            x1 = max(0, min(frame.shape[1] - 1, x1))
            x2 = max(x1 + 1, min(frame.shape[1], x2))
            y2 = max(y1 + 1, min(frame.shape[0], y2))
            coords_list.append((x1, y1, x2, y2))
    
    print("********************************************bbox_shift parameter adjustment**********************************************************")
    print(
        f"Total frames: {len(frames)}; bbox_shift: {upperbondrange}; "
        f"landmark_backend: {backend}"
    )
    print("*************************************************************************************************************************************")
    return coords_list,frames
    

if __name__ == "__main__":
    img_list = ["./results/lyria/00000.png","./results/lyria/00001.png","./results/lyria/00002.png","./results/lyria/00003.png"]
    crop_coord_path = "./coord_face.pkl"
    coords_list,full_frames = get_landmark_and_bbox(img_list)
    with open(crop_coord_path, 'wb') as f:
        pickle.dump(coords_list, f)
        
    for bbox, frame in zip(coords_list,full_frames):
        if bbox == coord_placeholder:
            continue
        x1, y1, x2, y2 = bbox
        crop_frame = frame[y1:y2, x1:x2]
        print('Cropped shape', crop_frame.shape)
        
        #cv2.imwrite(path.join(save_dir, '{}.png'.format(i)),full_frames[i][0][y1:y2, x1:x2])
    print(coords_list)
