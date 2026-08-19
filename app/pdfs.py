from __future__ import annotations

from decimal import Decimal
from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .utils import date_br, format_currency


def _money(value: Decimal | float | int | None) -> str:
    return format_currency(value or 0)


def _safe(value: object, fallback: str = '-') -> str:
    text = str(value or '').strip()
    return text or fallback


def _p(value: object, style: ParagraphStyle, fallback: str = '-') -> Paragraph:
    text = escape(_safe(value, fallback)).replace('\n', '<br/>')
    return Paragraph(text, style)


def _label_value(label: str, value: object, styles: dict[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(f'<b>{escape(label)}:</b> {escape(_safe(value))}', styles['small'])


def _section(title: str, styles: dict[str, ParagraphStyle]) -> list:
    return [Paragraph(escape(title).upper(), styles['section']), Spacer(1, 1.5 * mm)]


def _items_table(title: str, items: list, item_type: str, styles: dict[str, ParagraphStyle]) -> list:
    story = _section(title, styles)
    if not items:
        story.extend([Paragraph('Nenhum item informado.', styles['muted']), Spacer(1, 3 * mm)])
        return story

    if item_type == 'SERVICO':
        headers = ['#', 'SERVIÇO', 'HORAS/QTDE', 'V. UNIT.', 'V. TOTAL']
        widths = [8 * mm, 104 * mm, 24 * mm, 23 * mm, 27 * mm]
    else:
        headers = ['#', 'PRODUTO', 'UNIDADE', 'QTDE.', 'NCM', 'V. UNIT.', 'V. TOTAL']
        widths = [8 * mm, 73 * mm, 20 * mm, 19 * mm, 24 * mm, 23 * mm, 27 * mm]

    data = [[_p(header, styles['thead']) for header in headers]]
    for index, item in enumerate(items, start=1):
        if item_type == 'SERVICO':
            row = [_p(f'{index}.', styles['cell']), _p(item.descricao, styles['cell']), _p(item.quantidade, styles['cell_right']), _p(_money(item.valor_unitario), styles['cell_right']), _p(_money(item.total), styles['cell_right'])]
        else:
            product = getattr(item, 'product', None)
            row = [_p(f'{index}.', styles['cell']), _p(item.descricao, styles['cell']), _p(getattr(product, 'unidade', '-') if product else '-', styles['cell']), _p(item.quantidade, styles['cell_right']), _p(getattr(product, 'ncm', '-') if product else '-', styles['cell']), _p(_money(item.valor_unitario), styles['cell_right']), _p(_money(item.total), styles['cell_right'])]
        data.append(row)

    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 0.7, colors.black),
        ('LINEBELOW', (0, -1), (-1, -1), 0.35, colors.HexColor('#999999')),
        ('LINEBELOW', (0, 1), (-1, -2), 0.25, colors.HexColor('#cccccc')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2.2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.2),
        ('LEFTPADDING', (0, 0), (-1, -1), 1.2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1.2),
    ]))
    story.extend([table, Spacer(1, 3.5 * mm)])
    return story


def generate_work_order_pdf(order, service_items, part_items, company_name: str = 'ERP Auto Center', document_title: str = 'ORDEM DE SERVIÇO') -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=10 * mm, rightMargin=10 * mm, topMargin=9 * mm, bottomMargin=12 * mm, title=f'{document_title} {order.numero}', author=company_name)
    base = getSampleStyleSheet()
    styles = {
        'title': ParagraphStyle('pdf_title', parent=base['Normal'], fontName='Helvetica-Bold', fontSize=15, leading=16, textColor=colors.black),
        'company': ParagraphStyle('pdf_company', parent=base['Normal'], fontName='Helvetica', fontSize=7.5, leading=9, textColor=colors.black),
        'section': ParagraphStyle('pdf_section', parent=base['Normal'], fontName='Helvetica-Bold', fontSize=7.5, leading=9, textColor=colors.black, spaceBefore=1.5 * mm),
        'small': ParagraphStyle('pdf_small', parent=base['Normal'], fontName='Helvetica', fontSize=7.2, leading=9, textColor=colors.black),
        'thead': ParagraphStyle('pdf_thead', parent=base['Normal'], fontName='Helvetica-Bold', fontSize=6.8, leading=8, textColor=colors.black),
        'cell': ParagraphStyle('pdf_cell', parent=base['Normal'], fontName='Helvetica', fontSize=6.8, leading=8, textColor=colors.black),
        'cell_right': ParagraphStyle('pdf_cell_right', parent=base['Normal'], fontName='Helvetica', fontSize=6.8, leading=8, alignment=TA_RIGHT, textColor=colors.black),
        'muted': ParagraphStyle('pdf_muted', parent=base['Normal'], fontName='Helvetica-Oblique', fontSize=7, leading=8, textColor=colors.HexColor('#555555')),
        'total_label': ParagraphStyle('pdf_total_label', parent=base['Normal'], fontName='Helvetica-Bold', fontSize=7.5, leading=9, textColor=colors.black),
        'total': ParagraphStyle('pdf_total', parent=base['Normal'], fontName='Helvetica-Bold', fontSize=9, leading=10, alignment=TA_RIGHT, textColor=colors.black),
    }

    client = order.client
    client_name = order.client_nome or (client.nome if client else '-')
    header = Table([
        [Paragraph(escape(_safe(document_title)) + f' <b>#{escape(_safe(order.numero))}</b>', styles['title']), _p(f'DATA: {date_br(order.data_saida or order.data_entrada)}', styles['company'])],
        [Paragraph(f'<b>{escape(_safe(company_name))}</b><br/>ORDEM DE SERVIÇO<br/>Veículo: {escape(_safe(order.veiculo_descricao))} &nbsp;&nbsp; Placa: {escape(_safe(order.placa))}', styles['company']), _p(f'TÉCNICO: {order.employee.nome if order.employee else "-"}\nSTATUS: {str(order.status).replace("_", " ")}', styles['company'])],
    ], colWidths=[142 * mm, 48 * mm])
    header.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, 0), 0.7, colors.black), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('ALIGN', (1, 0), (1, -1), 'RIGHT'), ('TOPPADDING', (0, 0), (-1, -1), 1.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))

    client_table = Table([
        [_p('DADOS DO CLIENTE', styles['section']), '', _p(f'TÉCNICO: {order.employee.nome if order.employee else "-"}', styles['small']), _p(f'ATENDIMENTO: {str(order.status).replace("_", " ")}', styles['small'])],
        [_label_value('NOME', client_name, styles), _label_value('CPF/CNPJ', client.cpf_cnpj if client else '-', styles), _label_value('TELEFONE', client.telefone if client else '-', styles), _label_value('E-MAIL', client.email if client else '-', styles)],
        [_label_value('ENDEREÇO', client.endereco if client else '-', styles), '', _label_value('VEÍCULO', order.veiculo_descricao, styles), _label_value('PLACA', order.placa, styles)],
    ], colWidths=[74 * mm, 42 * mm, 40 * mm, 34 * mm])
    client_table.setStyle(TableStyle([('SPAN', (0, 0), (1, 0)), ('LINEBELOW', (0, 0), (-1, 0), 0.7, colors.black), ('LINEBELOW', (0, 2), (-1, 2), 0.25, colors.HexColor('#aaaaaa')), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 1.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 2)]))

    story: list = [header, Spacer(1, 3 * mm), client_table, Spacer(1, 2.5 * mm)]
    story.extend(_items_table('Serviços executados', service_items, 'SERVICO', styles))
    story.extend(_items_table('Produtos utilizados', part_items, 'PECA', styles))

    payment_name = order.payment_method.nome if order.payment_method else '-'
    service_quantity = sum((item.quantidade or 0) for item in service_items)
    part_quantity = sum((item.quantidade or 0) for item in part_items)
    payment = Table([
        [_p('DADOS DE PAGAMENTO', styles['section']), '', '', ''],
        [_p('TOTAL DE HORAS/QTDE DE SERVIÇOS', styles['thead']), _p(service_quantity, styles['cell_right']), _p('VALOR TOTAL DOS SERVIÇOS', styles['thead']), _p(_money(order.total_servicos), styles['cell_right'])],
        [_p('TOTAL DE PRODUTOS', styles['thead']), _p(part_quantity, styles['cell_right']), _p('VALOR TOTAL DOS PRODUTOS', styles['thead']), _p(_money(order.total_pecas), styles['cell_right'])],
        ['', '', _p('VALOR TOTAL DA O.S.', styles['total_label']), _p(_money(order.total_geral), styles['total'])],
        [_p('PAGAMENTO', styles['thead']), _p(payment_name, styles['cell']), _p('PARCELAS', styles['thead']), _p(order.installment_count or 1, styles['cell'])],
    ], colWidths=[70 * mm, 25 * mm, 61 * mm, 34 * mm])
    payment.setStyle(TableStyle([('SPAN', (0, 0), (-1, 0)), ('LINEBELOW', (0, 0), (-1, 0), 0.7, colors.black), ('LINEABOVE', (2, 3), (3, 3), 0.5, colors.black), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('ALIGN', (1, 1), (1, -1), 'RIGHT'), ('ALIGN', (3, 1), (3, -1), 'RIGHT'), ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 2)]))
    story.extend([payment, Spacer(1, 2.5 * mm), Paragraph(f'<b>OBSERVAÇÕES:</b> {escape(_safe(order.observacoes, "Sem observações."))}', styles['small'])])

    def draw_footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#999999'))
        canvas.setLineWidth(0.35)
        canvas.line(document.leftMargin, 7 * mm, A4[0] - document.rightMargin, 7 * mm)
        canvas.setFont('Helvetica', 6.5)
        canvas.setFillColor(colors.HexColor('#555555'))
        canvas.drawString(document.leftMargin, 4 * mm, 'Documento gerado pelo sistema. Este recibo não substitui a nota fiscal oficial.')
        canvas.drawRightString(A4[0] - document.rightMargin, 4 * mm, f'Página {canvas.getPageNumber()}')
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buffer.getvalue()
