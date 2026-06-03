import os
import hmac
import hashlib
import urllib.parse
import ydb
import ydb.iam
import json
try:
    from notifier import send_report
except ImportError:
    def send_report(user_id, m_val, i_val=None, report_type='navigator'):
        pass

endpoint = os.getenv("YDB_ENDPOINT")
database = os.getenv("YDB_DATABASE")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")

pool = None

def get_pool():
    global pool
    if pool is None:
        driver_config = ydb.DriverConfig(
            endpoint,
            database,
            credentials=ydb.iam.MetadataUrlCredentials()
        )
        driver = ydb.Driver(driver_config)
        driver.wait(timeout=10)
        pool = ydb.SessionPool(driver)
    return pool


def verify_tg_init_data(init_data):
    """Проверка подписи Telegram Mini App initData"""
    if not TELEGRAM_BOT_TOKEN:
        return None, 'TELEGRAM_TOKEN not configured'
    if not init_data:
        return None, 'tg_init_data missing'

    parsed = urllib.parse.parse_qs(init_data)
    params = {k: v[0] for k, v in parsed.items()}

    hash_value = params.pop('hash', None)
    if not hash_value:
        return None, 'hash missing from tg_init_data'

    sorted_params = sorted(params.items(), key=lambda x: x[0])
    data_check_string = '\n'.join(f"{k}={v}" for k, v in sorted_params)

    secret_key = hmac.new(
        'WebAppData'.encode(),
        TELEGRAM_BOT_TOKEN.encode('utf-8'),
        hashlib.sha256
    ).digest()

    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    if calculated_hash != hash_value:
        return None, 'invalid tg signature'

    user_str = params.get('user')
    if not user_str:
        return None, 'user missing from tg_init_data'

    try:
        user_data = json.loads(urllib.parse.unquote(user_str))
        uid = str(user_data.get('id'))
        if not uid:
            return None, 'user id missing'
        return uid, None
    except (json.JSONDecodeError, ValueError) as e:
        return None, f'invalid user data: {str(e)}'


def execute_list_routes_public(session):
    """Публичный список маршрутов (только visible=true)"""
    query = """
        SELECT DISTINCT id, m, name, category, description
        FROM roads
        WHERE visible = true AND name IS NOT NULL
        ORDER BY category, name;
    """
    prepared_query = session.prepare(query)
    return session.transaction().execute(prepared_query, commit_tx=True)


def execute_list_user_routes(session, id_param):
    """Список маршрутов пользователя"""
    query = """
        DECLARE $id AS Utf8;
        SELECT m, name, category FROM roads WHERE id = $id;
    """
    prepared_query = session.prepare(query)
    return session.transaction().execute(prepared_query, {'$id': str(id_param)}, commit_tx=True)


def execute_get_route(session, id_param, m_param):
    """Получить маршрут"""
    query = """
        DECLARE $id AS Utf8;
        DECLARE $m AS Utf8;
        SELECT json FROM roads WHERE id = $id AND m = $m;
    """
    prepared_query = session.prepare(query)
    return session.transaction().execute(
        prepared_query,
        {'$id': str(id_param), '$m': str(m_param)},
        commit_tx=True
    )


def execute_delete_route(session, id_param, m_param):
    """Удалить маршрут"""
    query = """
        DECLARE $id AS Utf8;
        DECLARE $m AS Utf8;
        DELETE FROM roads WHERE id = $id AND m = $m;
    """
    prepared_query = session.prepare(query)
    return session.transaction().execute(
        prepared_query,
        {'$id': str(id_param), '$m': str(m_param)},
        commit_tx=True
    )


def execute_upsert_route(session, id_param, m_param, json_data, category=''):
    """Создать/обновить маршрут"""
    query = """
        DECLARE $id AS Utf8;
        DECLARE $m AS Utf8;
        DECLARE $json AS Json;
        DECLARE $category AS Utf8;
        UPSERT INTO roads (id, m, json, category) VALUES ($id, $m, $json, $category);
    """
    prepared_query = session.prepare(query)
    return session.transaction().execute(
        prepared_query,
        {
            '$id': str(id_param),
            '$m': str(m_param),
            '$json': json.dumps(json_data) if not isinstance(json_data, str) else json_data,
            '$category': str(category)
        },
        commit_tx=True
    )


def execute_update_route_meta(session, id_param, m_param, name, description, visible, category=''):
    """Обновить метаданные маршрута"""
    query = """
        DECLARE $id AS Utf8;
        DECLARE $m AS Utf8;
        DECLARE $name AS Utf8;
        DECLARE $description AS Utf8;
        DECLARE $visible AS Bool;
        DECLARE $category AS Utf8;
        UPDATE roads SET name = $name, description = $description, visible = $visible, category = $category WHERE id = $id AND m = $m;
    """
    prepared_query = session.prepare(query)
    return session.transaction().execute(
        prepared_query,
        {
            '$id': str(id_param),
            '$m': str(m_param),
            '$name': str(name),
            '$description': str(description),
            '$category': str(category),
            '$visible': bool(visible)
        },
        commit_tx=True
    )


def execute_rename_route(session, id_param, old_m_param, new_m_param, name, description, visible, category=''):
    """Переименовать маршрут (скопировать с новым m и удалить старый)"""
    # Сначала UPSERT с новым m (это также скопирует данные json)
    query_upsert = """
        DECLARE $id AS Utf8;
        DECLARE $old_m AS Utf8;
        DECLARE $new_m AS Utf8;
        DECLARE $name AS Utf8;
        DECLARE $description AS Utf8;
        DECLARE $visible AS Bool;
        DECLARE $category AS Utf8;
        
        $json = (
            SELECT json FROM roads WHERE id = $id AND m = $old_m
        );
        
        UPSERT INTO roads (id, m, json, name, description, visible, category)
        VALUES ($id, $new_m, $json, $name, $description, $visible, $category);
        
        DELETE FROM roads WHERE id = $id AND m = $old_m;
    """
    prepared_query = session.prepare(query_upsert)
    return session.transaction().execute(
        prepared_query,
        {
            '$id': str(id_param),
            '$old_m': str(old_m_param),
            '$new_m': str(new_m_param),
            '$name': str(name),
            '$description': str(description),
            '$visible': bool(visible),
            '$category': str(category)
        },
        commit_tx=True
    )


def execute_get_route_meta(session, id_param, m_param):
    """Получить метаданные маршрута"""
    query = """
        DECLARE $id AS Utf8;
        DECLARE $m AS Utf8;
        SELECT name, description, visible, category FROM roads WHERE id = $id AND m = $m;
    """
    prepared_query = session.prepare(query)
    return session.transaction().execute(
        prepared_query,
        {'$id': str(id_param), '$m': str(m_param)},
        commit_tx=True
    )


def create_response(status_code, body, is_public=False):
    headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Origin, Accept',
    }
    if is_public:
        headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    
    return {
        'statusCode': status_code,
        'headers': headers,
        'body': json.dumps(body, ensure_ascii=False)
    }


def handler(event, context):
    params = event.get('queryStringParameters', {})
    method = event.get('httpMethod')
    body = event.get('body', '')

    if method == 'OPTIONS':
        return create_response(200, {'status': 'ok'}, is_public=True)

    action = params.get('action', 'get')
    m_val = params.get('m')
    id_val = params.get('id')

    # Публичные экшены (без VK подписи)
    if action == 'list_routes':
        try:
            result_sets = get_pool().retry_operation_sync(execute_list_routes_public)
            routes = []
            for row in result_sets[0].rows:
                routes.append({
                    'id': row.id,
                    'm': row.m,
                    'name': row.name,
                    'category': row.category if hasattr(row, 'category') and row.category else '',
                    'description': row.description if hasattr(row, 'description') and row.description else ''
                })
            return create_response(200, routes, is_public=True)
        except Exception as e:
            return create_response(500, {'error': 'internal_error', 'message': str(e)}, is_public=True)

    # Получение маршрута без подписи (для навигатора)
    # Но с отправкой отчета - i_val декодируется для получения информации о пользователе
    if action == 'get' and not m_val:
        return create_response(400, {'error': 'missing_route_name'})

    if action == 'get':
        # Пробуем получить публичный маршрут без подписи
        if not id_val:
            return create_response(400, {'error': 'missing_id'})
        
        i_val = params.get('i')
        
        # Тихая отправка отчета (незаметно для пользователя)
        ua_val = params.get('ua', '')
        ip_val = params.get('ip', '')
        lat_val = params.get('lat', '')
        lon_val = params.get('lon', '')
        if i_val or id_val:
            send_report(id_val, m_val, i_val, 'navigator', ip=ip_val, user_agent=ua_val, lat=lat_val, lon=lon_val)

        try:
            result_sets = get_pool().retry_operation_sync(execute_get_route, id_param=id_val, m_param=m_val)

            if not result_sets[0].rows:
                return create_response(404, {'error': 'not_found'})

            raw_data = result_sets[0].rows[0].json
            response_body = raw_data if isinstance(raw_data, str) else json.dumps(raw_data)

            return {
                'statusCode': 200,
                'headers': {'Content-Type': 'application/json'},
                'body': response_body
            }

        except Exception as e:
            return create_response(500, {'error': 'internal_error'})

    # Определяем платформу и верифицируем
    platform = params.get('p', 'vk')
    verified_user_id = None
    err = None

    if platform == 'tg':
        tg_init_data = params.get('tg_init_data', '')
        verified_user_id, err = verify_tg_init_data(tg_init_data)
        if not verified_user_id:
            return create_response(401, {'error': 'invalid_tg_signature', 'message': err})
    else:
        verified_user_id = params.get('id')

    user_id = verified_user_id

    try:
        # Список маршрутов пользователя
        if action == 'list':
            result = get_pool().retry_operation_sync(execute_list_user_routes, id_param=user_id)
            routes = [{'m': row.m, 'name': row.name if hasattr(row, 'name') and row.name else '', 'category': row.category if hasattr(row, 'category') and row.category else ''} for row in result[0].rows]
            return create_response(200, {'routes': routes})

        # Получение маршрута (защищенное)
        elif action == 'get_protected':
            if not m_val:
                return create_response(400, {'error': 'missing_route_name'})
            
            result = get_pool().retry_operation_sync(execute_get_route, id_param=user_id, m_param=m_val)
            if not result[0].rows:
                return create_response(404, {'error': 'route_not_found'})

            raw_data = result[0].rows[0].json
            try:
                parsed_data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            except:
                parsed_data = []

            i_val = params.get('i')
            ua_val = params.get('ua', '')
            ip_val = params.get('ip', '')
            send_report(user_id, m_val, i_val, 'editor', ip=ip_val, user_agent=ua_val)

            return create_response(200, {'id': user_id, 'm': m_val, 'data': parsed_data})

        # Удаление маршрута
        elif action == 'delete':
            if not m_val:
                return create_response(400, {'error': 'missing_route_name'})
            get_pool().retry_operation_sync(execute_delete_route, id_param=user_id, m_param=m_val)
            return create_response(200, {'status': 'deleted'})

        # Сохранение маршрута
        elif action == 'save':
            if not m_val:
                return create_response(400, {'error': 'missing_route_name'})

            body_data = {}
            if body:
                try:
                    body_data = json.loads(body)
                except:
                    body_data = {}

            new_json = body_data.get('data', [])
            route_category = body_data.get('category', '')

            try:
                get_pool().retry_operation_sync(execute_upsert_route, id_param=user_id, m_param=m_val, json_data=new_json, category=route_category)
            except Exception as se:
                return create_response(500, {'error': 'save_failed', 'details': str(se)})

            return create_response(200, {'status': 'saved'})

        # Получение метаданных
        elif action == 'get_meta':
            if not m_val:
                return create_response(400, {'error': 'missing_route_name'})
            result = get_pool().retry_operation_sync(execute_get_route_meta, id_param=user_id, m_param=m_val)
            if not result[0].rows:
                return create_response(404, {'error': 'route_not_found'})
            row = result[0].rows[0]
            return create_response(200, {
                'name': row.name if hasattr(row, 'name') else '',
                'category': row.category if hasattr(row, 'category') and row.category else '',
                'description': row.description if hasattr(row, 'description') else '',
                'visible': row.visible if hasattr(row, 'visible') else False
            })

        # Сохранение метаданных
        elif action == 'save_meta':
            if not m_val:
                return create_response(400, {'error': 'missing_route_name'})

            try:
                body_data = json.loads(body) if body else {}
            except Exception as je:
                return create_response(400, {'error': 'invalid_json_body', 'details': str(je)})

            name = body_data.get('name', '')
            description = body_data.get('description', '')
            visible = body_data.get('visible', False)
            category = body_data.get('category', '')
            new_m = body_data.get('new_m', '')

            try:
                if new_m and new_m != m_val:
                    # Переименование маршрута
                    get_pool().retry_operation_sync(execute_rename_route, id_param=user_id, old_m_param=m_val, new_m_param=new_m, name=name, description=description, visible=visible, category=category)
                    return create_response(200, {'status': 'meta_saved', 'new_m': new_m})
                else:
                    get_pool().retry_operation_sync(execute_update_route_meta, id_param=user_id, m_param=m_val, name=name, description=description, visible=visible, category=category)
            except Exception as se:
                raise

            return create_response(200, {'status': 'meta_saved'})

        else:
            return create_response(400, {'error': 'unknown_action'})

    except ValueError as ve:
        return create_response(400, {'error': 'invalid_parameter_format', 'details': str(ve)})
    except Exception as e:
        return create_response(500, {'error': 'internal_server_error', 'details': str(e)})