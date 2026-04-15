import cv2
import sys
sys.path.insert(0, '.')
from app.ocr import _ocr_frame, _enhance_for_ocr

img = cv2.imread('tools/ocr_debug/ocr_1435_p125_fail.jpg')
h, w = img.shape[:2]

# Simulate ROI crop (top=24%, bottom=51%)
y1 = int(h * 24 / 100)
y2 = int(h * 51 / 100)
x1 = int(w * 22 / 100)
x2 = int(w * 92 / 100)
cropped = img[y1:y2, x1:x2]

print("=== Without enhancement ===")
text1 = _ocr_frame(cropped)
print(text1)

print("\n=== With enhancement ===")
enhanced = _enhance_for_ocr(cropped)
text2 = _ocr_frame(enhanced)
print(text2)

print("\n=== Check ===")
print("'9.19' in raw:", '9.19' in text1 or '919' in text1.replace(' ', '').replace('.', ''))
print("'9.19' in enhanced:", '9.19' in text2 or '919' in text2.replace(' ', '').replace('.', ''))
