from __future__ import annotations
from io import BytesIO
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .utils import date_br, format_currency

def _money(value: Decimal | float | int | None) -> str:
    return format_currency(value or 0)

def _safe(text: object, fallback: str = '-') -> str:
    value = str(text or '').strip()
    return value or fallback

def _paragraph(text: object, style: ParagraphStyle) -> Paragraph:
    safe = _safe(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br/>')
    return Paragraph(safe, style)

def _meta_table(order, styles: dict[str, ParagraphStyle]) -> Table:
    payment_name = order.payment_method.nome if order.payment_method else '-'
    payment_detail = payment_name
    if order.payment_method and getattr(order.payment_method, 'permite_parcelamento', False):
        parcelas = max(order.installment_count or 1, 1)
        payment_detail = f'{payment_name} — {parcelas}x de {_money((order.total_geral or 0) / parcelas)}'

    rows = [
        [_paragraph('Cliente', styles['label']), _paragraph(order.client_nome or (order.client.nome if order.client else '-'), styles['value'])],
        [_paragraph('Funcionário', styles['label']), _paragraph(order.employee.nome if order.employee else '-', styles['value'])],
        [_paragraph('Veículo', styles['label']), _paragraph(order.veiculo_descricao or '-', styles['value'])],
        [_paragraph('Placa', styles['label']), _paragraph(order.placa or '-', styles['value'])],
        [_paragraph('Pagamento', styles['label']), _paragraph(payment_detail, styles['value'])],
        [_paragraph('Entrada', styles['label']), _paragraph(date_br(order.data_entrada), styles['value'])],
        [_paragraph('Status', styles['label']), _paragraph(str(order.status).replace('_', ' '), styles['value'])],
    ]
    table = Table(rows, colWidths=[34 * mm, 140 * mm], repeatRows=0)
    
    # Ventriloc Theme for Information Block
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#efefef')), # Ash Surface
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.HexColor('#efefef'), colors.HexColor('#f5f5f5')]), # Ash / Fog
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#e8e8e8')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e8e8e8')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    return table

def _items_table(title: str, items: list, empty_label: str, styles: dict[str, ParagraphStyle]) -> list:
    story: list = [Paragraph(title, styles['section']), Spacer(1, 4 * mm)]
    if not items:
        story.append(Paragraph(empty_label, styles['muted']))
        story.append(Spacer(1, 4 * mm))
        return story

    data = [[
        Paragraph('Descrição', styles['thead']),
        Paragraph('Qtd.', styles['thead']),
        Paragraph('Valor un.', styles['thead']),
        Paragraph('Total', styles['thead']),
    ]]
    for item in items:
        data.append([
            _paragraph(item.descricao, styles['cell']),
            Paragraph(_safe(item.quantidade), styles['cell_center']),
            Paragraph(_money(item.valor_unitario), styles['cell_right']),
            Paragraph(_money(item.total), styles['cell_right_bold']),
        ])
    
    table = Table(data, colWidths=[108 * mm, 18 * mm, 28 * mm, 28 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#efefef')), # Ash Header
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#202020')), # Graphite Text
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#e8e8e8')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e8e8e8')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.extend([table, Spacer(1, 5 * mm)])
    return story

def _summary_table(order, styles: dict[str, ParagraphStyle]) -> Table:
    data = [
        [Paragraph('Resumo financeiro', styles['section_inline']), '', ''],
        [Paragraph('Total de serviços', styles['label']), Paragraph(_money(order.total_servicos), styles['cell_right']), ''],
        [Paragraph('Total de peças', styles['label']), Paragraph(_money(order.total_pecas), styles['cell_right']), ''],
        [Paragraph('Total geral', styles['label']), Paragraph(_money(order.total_geral), styles['cell_right_ember']), ''],
    ]
    table = Table(data, colWidths=[70 * mm, 45 * mm, 67 * mm])
    table.setStyle(TableStyle([
        ('SPAN', (0, 0), (-1, 0)),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#202020')), # Graphite Header
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#e8e8e8')),
        ('INNERGRID', (0, 1), (-1, -1), 0.5, colors.HexColor('#e8e8e8')),
        ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    return table

def generate_work_order_pdf(order, service_items, part_items, company_name: str = 'ERP Auto Center') -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title=f'Ordem de Serviço {order.numero}',
        author=company_name,
    )
    base = getSampleStyleSheet()

    # Ventriloc Editorial Typography Config
    styles: dict[str, ParagraphStyle] = {
        'title': ParagraphStyle('title', parent=base['Heading1'], fontName='Helvetica-Bold', fontSize=20, leading=24, textColor=colors.white, spaceAfter=0),
        'subtitle': ParagraphStyle('subtitle', parent=base['Normal'], fontName='Helvetica', fontSize=9, leading=12, textColor=colors.white, spaceAfter=0),
        'section': ParagraphStyle('section', parent=base['Heading2'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=colors.HexColor('#202020'), spaceBefore=2 * mm, spaceAfter=2 * mm),
        'section_inline': ParagraphStyle('section_inline', parent=base['Heading2'], fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=colors.white),
        'label': ParagraphStyle('label', parent=base['BodyText'], fontName='Helvetica-Bold', fontSize=9.5, leading=12, textColor=colors.HexColor('#202020')),
        'value': ParagraphStyle('value', parent=base['BodyText'], fontName='Helvetica', fontSize=9.5, leading=12.5, textColor=colors.HexColor('#4d4d4d')),
        'muted': ParagraphStyle('muted', parent=base['BodyText'], fontName='Helvetica-Oblique', fontSize=9, leading=12, textColor=colors.HexColor('#828282')),
        'thead': ParagraphStyle('thead', parent=base['BodyText'], fontName='Helvetica-Bold', fontSize=9, leading=11, textColor=colors.HexColor('#202020')),
        'cell': ParagraphStyle('cell', parent=base['BodyText'], fontName='Helvetica', fontSize=9, leading=11.5, textColor=colors.HexColor('#4d4d4d')),
        'cell_center': ParagraphStyle('cell_center', parent=base['BodyText'], fontName='Helvetica', fontSize=9, leading=11.5, alignment=1, textColor=colors.HexColor('#4d4d4d')),
        'cell_right': ParagraphStyle('cell_right', parent=base['BodyText'], fontName='Helvetica', fontSize=9, leading=11.5, alignment=TA_RIGHT, textColor=colors.HexColor('#4d4d4d')),
        'cell_right_bold': ParagraphStyle('cell_right_bold', parent=base['BodyText'], fontName='Helvetica-Bold', fontSize=9, leading=11.5, alignment=TA_RIGHT, textColor=colors.HexColor('#202020')),
        'cell_right_ember': ParagraphStyle('cell_right_ember', parent=base['BodyText'], fontName='Helvetica-Bold', fontSize=10, leading=11.5, alignment=TA_RIGHT, textColor=colors.HexColor('#ff682c')), # Laranja Ember para destaque do total
    }

    header = Table([
        [
            Paragraph('ORDEM DE SERVIÇO', styles['title']),
            Paragraph(
                f'Número: {_safe(order.numero)}<br/>Entrada: {date_br(order.data_entrada)}<br/>Status: {_safe(str(order.status).replace("_", " "))}',
                ParagraphStyle('header_right', parent=styles['subtitle'], alignment=TA_RIGHT),
            ),
        ],
        [Paragraph(f'Documento gerado pelo {_safe(company_name)}', styles['subtitle']), ''],
    ], colWidths=[115 * mm, 65 * mm])
    
    header.setStyle(TableStyle([
        ('SPAN', (0, 1), (1, 1)),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#202020')), # Graphite Header
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#202020')),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))

    story: list = [header, Spacer(1, 5 * mm), Paragraph('Dados principais', styles['section']), Spacer(1, 2 * mm), _meta_table(order, styles), Spacer(1, 5 * mm)]
    story.extend(_items_table('Serviços realizados', service_items, 'Nenhum serviço informado.', styles))
    story.extend(_items_table('Peças usadas', part_items, 'Nenhuma peça informada.', styles))
    story.extend([_summary_table(order, styles), Spacer(1, 5 * mm), Paragraph('Observações', styles['section']), Spacer(1, 2 * mm)])

    obs = Table([[_paragraph(order.observacoes or 'Sem observações registradas.', styles['value'])]], colWidths=[180 * mm])
    obs.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.white),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#e8e8e8')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(obs)

    def draw_footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#e8e8e8')) # Mist Line
        canvas.line(doc.leftMargin, 11 * mm, A4[0] - doc.rightMargin, 11 * mm)
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#828282')) # Slate Text
        canvas.drawString(doc.leftMargin, 7 * mm, f'{_safe(company_name)} — ordem de serviço gerada via sistema')
        canvas.drawRightString(A4[0] - doc.rightMargin, 7 * mm, f'Página {canvas.getPageNumber()}')
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buffer.getvalue()
