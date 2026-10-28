from docx import Document
from docx.shared import RGBColor,Pt
from docx.oxml.ns import qn
p='output/report/AuthenTra_Mini_Project_Report.docx'
d=Document(p)
for name in ['Normal','Heading 1','Heading 2']:
 s=d.styles[name]; f=s.element.rPr.rFonts
 for k in list(f.attrib):
  if 'Theme' in k: del f.attrib[k]
 for k in ['ascii','hAnsi','eastAsia','cs']: f.set(qn('w:'+k),'Times New Roman')
for sec in d.sections[1:]:
 for p1 in sec.footer.paragraphs:
  for r in p1.runs:r.font.name='Times New Roman';r.font.size=Pt(11);r.font.color.rgb=RGBColor(0,80,255)
d.save(p)
