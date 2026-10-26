"""Create unique, explicitly labeled documents for real local browser tests."""
from pathlib import Path
from uuid import uuid4
from reportlab.pdfgen import canvas

root = Path(__file__).resolve().parents[2]
(root / '.local').mkdir(exist_ok=True)
for name in ['first', 'second']:
    c = canvas.Canvas(str(root / '.local' / ('e2e-' + name + '.pdf')))
    c.drawString(50, 750, 'DEMONSTRATION CERTIFICATE - UPLOAD TEST')
    c.drawString(50, 710, 'Browser test ' + name + ' ' + uuid4().hex)
    c.save()
from PIL import Image
Image.new('RGB', (120, 80), 'white').save(root / '.local/e2e-image.jpg')
