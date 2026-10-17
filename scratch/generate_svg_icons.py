import cv2

img = cv2.imread('docs/image/logo.jpg', cv2.IMREAD_GRAYSCALE)
img = cv2.resize(img, (500, 500), interpolation=cv2.INTER_CUBIC)
_, thresh = cv2.threshold(img, 128, 255, cv2.THRESH_BINARY)
contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_TC89_KCOS)

svg_paths = []
for cnt in contours:
    # slight smoothing
    epsilon = 0.002 * cv2.arcLength(cnt, True)
    approx = cv2.approxPolyDP(cnt, epsilon, True)
    d = []
    for i, pt in enumerate(approx):
        x, y = pt[0][0], pt[0][1]
        cmd = 'M' if i == 0 else 'L'
        d.append(f'{cmd}{x} {y}')
    d.append('Z')
    svg_paths.append(' '.join(d))

svg_content = f'''<svg xmlns="http://www.w3.org/2000/svg" width="500" height="500" viewBox="0 0 500 500" fill="none">
  <rect width="500" height="500" rx="100" fill="#0b0e14"/>
  <path d="{svg_paths[0]}" fill="#d9a441"/>
  <path d="{svg_paths[1]}" fill="#d9a441"/>
</svg>'''

with open('frontend/icons/icon.svg', 'w') as f:
    f.write(svg_content)
with open('frontend/icons/icon-maskable.svg', 'w') as f:
    f.write(svg_content)

# Also generate a standalone symbol version (without rect background) for inline brand header!
brand_symbol_svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 500 500" fill="none">
  <path d="{svg_paths[0]}" fill="currentColor"/>
  <path d="{svg_paths[1]}" fill="currentColor"/>
</svg>'''

with open('frontend/icons/brand-symbol.svg', 'w') as f:
    f.write(brand_symbol_svg)

print('Successfully generated icon.svg, icon-maskable.svg, and brand-symbol.svg')
