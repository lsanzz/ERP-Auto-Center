import re
from datetime import date

from ..models import Client, WorkOrder, Budget, db
from .models import Vehicle, OdometerReading, VehicleOwnershipHistory

CATEGORIES = ('AUTOMOVEL', 'MOTO', 'CAMINHAO', 'UTILITARIO', 'ONIBUS', 'MAQUINA', 'OUTRO')
TEXT_FIELDS = {'descricao': 160, 'chassi': 30, 'renavam': 20, 'marca': 80,
               'modelo': 100, 'versao': 100, 'motor': 80, 'combustivel': 40,
               'cambio': 40, 'cor': 40, 'observacoes': 10000}


def normalize_plate(value):
    value = re.sub(r'[\s-]', '', str(value or '')).upper()
    if value and not re.fullmatch(r'[A-Z]{3}[0-9][A-Z0-9][0-9]{2}', value):
        raise ValueError('Informe uma placa válida (ABC1234 ou ABC1D23) ou deixe em branco.')
    return value or None


def save_vehicle(vehicle, data, user_id):
    try:
        client_id = int(data.get('client_id', vehicle.client_id))
    except (TypeError, ValueError):
        raise ValueError('Selecione um cliente cadastrado.')
    if not db.session.get(Client, client_id):
        raise ValueError('Cliente não encontrado.')
    plate = normalize_plate(data.get('placa', vehicle.placa))
    if plate:
        other = Vehicle.query.filter_by(client_id=client_id, placa=plate).first()
        if other and other.id != vehicle.id:
            raise ValueError('Este cliente já possui um veículo com essa placa.')
    values = {}
    for field, limit in TEXT_FIELDS.items():
        value = str(data.get(field, getattr(vehicle, field)) or '').strip()
        if len(value) > limit:
            raise ValueError(f'O campo {field} aceita até {limit} caracteres.')
        values[field] = value or None
    if not values['descricao']:
        raise ValueError('Informe a descrição do veículo.')
    for field in ('ano_fabricacao', 'ano_modelo'):
        raw = data.get(field, getattr(vehicle, field))
        try:
            values[field] = int(raw) if raw not in (None, '') else None
        except (TypeError, ValueError):
            raise ValueError('Informe um ano válido.')
        if values[field] is not None and not 1900 <= values[field] <= date.today().year + 2:
            raise ValueError('Ano fora do intervalo permitido.')
    category = data.get('categoria', vehicle.categoria) or 'AUTOMOVEL'
    if category not in CATEGORIES:
        raise ValueError('Categoria de veículo inválida.')
    previous = vehicle.client_id
    vehicle.client_id, vehicle.placa, vehicle.categoria = client_id, plate, category
    for field, value in values.items():
        setattr(vehicle, field, value)
    if 'ativo' in data:
        vehicle.ativo = data['ativo'] in (True, 'true', '1', 'on')
    db.session.add(vehicle)
    db.session.flush()
    if previous != client_id:
        db.session.add(VehicleOwnershipHistory(vehicle_id=vehicle.id,
                       previous_client_id=previous, client_id=client_id, user_id=user_id))
    if data.get('quilometragem') not in (None, ''):
        record_odometer(vehicle, data['quilometragem'], user_id)
    return vehicle


def record_odometer(vehicle, raw, user_id, recorded_on=None, observation=None):
    try:
        km = int(str(raw))
    except (TypeError, ValueError):
        raise ValueError('A quilometragem deve ser um número inteiro.')
    if not 0 <= km <= 2147483647:
        raise ValueError('Quilometragem fora do intervalo permitido.')
    day = recorded_on or date.today()
    if day > date.today():
        raise ValueError('A leitura não pode ter data futura.')
    before = OdometerReading.query.filter(OdometerReading.vehicle_id == vehicle.id,
                OdometerReading.recorded_on <= day).order_by(
                OdometerReading.recorded_on.desc(), OdometerReading.quilometragem.desc()).first()
    after = OdometerReading.query.filter(OdometerReading.vehicle_id == vehicle.id,
                OdometerReading.recorded_on > day).order_by(
                OdometerReading.recorded_on, OdometerReading.quilometragem).first()
    if (before and km < before.quilometragem) or (after and km > after.quilometragem):
        raise ValueError('A quilometragem deve respeitar a sequência das leituras existentes.')
    if before and before.recorded_on == day and before.quilometragem == km:
        return before
    reading = OdometerReading(vehicle_id=vehicle.id, quilometragem=km, recorded_on=day,
                              user_id=user_id, observacoes=(observation or '')[:255] or None)
    db.session.add(reading)
    if not after:
        vehicle.quilometragem = km
    # Also increments the optimistic version when recording historical readings.
    from datetime import datetime
    vehicle.updated_at = datetime.now()
    return reading


def link_vehicle(document, data):
    """Keep legacy snapshots, validate owner and link explicitly selected vehicles."""
    from sqlalchemy import inspect
    owner_changed = inspect(document).attrs.client_id.history.has_changes()
    if 'vehicle_id' not in data:
        if document.vehicle_id:
            existing = db.session.get(Vehicle, document.vehicle_id)
            # Legacy integrations may change text without knowing vehicle_id.
            if existing and (document.client_id != existing.client_id or
                             normalize_plate(document.placa) != existing.placa):
                document.vehicle = None
        return
    raw = data.get('vehicle_id')
    if not raw:
        document.vehicle = None
        return
    try:
        with db.session.no_autoflush:
            vehicle = db.session.get(Vehicle, int(raw))
    except (TypeError, ValueError):
        raise ValueError('Veículo selecionado inválido.')
    if not vehicle:
        raise ValueError('Veículo não encontrado.')
    # Existing historical links remain usable after transfer of ownership.
    same_link = document.vehicle_id == vehicle.id and not owner_changed
    if vehicle.client_id != document.client_id and not same_link:
        raise ValueError('O veículo selecionado não pertence ao cliente informado.')
    if not vehicle.ativo and not same_link:
        raise ValueError('O veículo selecionado está inativo.')
    document.vehicle = vehicle
    if not same_link:
        document.placa = vehicle.placa
        document.veiculo_descricao = vehicle.descricao


def import_legacy_vehicles():
    """Idempotent backfill; client+plate only, ambiguous descriptions need review."""
    groups, conflicts = {}, []
    for model in (Budget, WorkOrder):
        for document in model.query.filter(model.vehicle_id.is_(None)).yield_per(200):
            try:
                plate = normalize_plate(document.placa)
            except ValueError:
                plate = None
            if not plate or not document.client_id:
                conflicts.append({'tipo': model.__name__, 'id': document.id, 'motivo': 'Sem placa válida/cliente'})
                continue
            groups.setdefault((document.client_id, plate), []).append(document)
    created = linked = 0
    for (client_id, plate), documents in groups.items():
        descriptions = {d.veiculo_descricao.strip().casefold() for d in documents if (d.veiculo_descricao or '').strip()}
        if len(descriptions) > 1:
            conflicts.append({'cliente': client_id, 'placa': plate, 'motivo': 'Descrições divergentes'})
            continue
        vehicle = Vehicle.query.filter_by(client_id=client_id, placa=plate).first()
        if vehicle and descriptions and vehicle.descricao.strip().casefold() not in descriptions:
            conflicts.append({'cliente': client_id, 'placa': plate, 'motivo': 'Cadastro existente divergente'})
            continue
        if not vehicle:
            description = next((d.veiculo_descricao.strip() for d in documents if (d.veiculo_descricao or '').strip()), plate)
            vehicle = save_vehicle(Vehicle(), {'client_id': client_id, 'placa': plate, 'descricao': description}, None)
            created += 1
        for document in documents:
            document.vehicle = vehicle
            linked += 1
    db.session.flush()
    return {'criados': created, 'vinculados': linked, 'conflitos': conflicts}
