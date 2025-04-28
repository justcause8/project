import xml.etree.ElementTree as ET
import folium
import os
import pandas as pd
import requests

def fetch_bus_stops(bounds):
    """
    Загружает данные остановок общественного транспорта через Overpass API.

    :param bounds: Границы области в формате (min_lat, min_lon, max_lat, max_lon)
    :return: Список координат остановок [(lat1, lon1), (lat2, lon2), ...]
    """
    min_lat, min_lon, max_lat, max_lon = bounds
    overpass_url = "https://overpass-api.de/api/interpreter"
    overpass_query = f"""
    [out:json];
    (
        node["highway"="bus_stop"]({min_lat},{min_lon},{max_lat},{max_lon});
        node["public_transport"="stop_position"]({min_lat},{min_lon},{max_lat},{max_lon});
    );
    out center;
    """
    try:
        response = requests.get(overpass_url, params={'data': overpass_query})
        response.raise_for_status()
        data = response.json()
        bus_stops = []
        for element in data.get("elements", []):
            if element.get("type") == "node" and "lat" in element and "lon" in element:
                bus_stops.append((element["lat"], element["lon"]))
        return bus_stops
    except Exception as e:
        print(f"Ошибка при загрузке данных остановок через Overpass API: {e}")
        return []

def load_route_data(excel_file):
    """
    Загружает данные о маршрутах из Excel-файла.

    :param excel_file: Путь к файлу Excel
    :return: Словарь с данными о маршрутах, где ключ — ID маршрута
    """
    df = pd.read_excel(excel_file)
    route_data = {}
    for _, row in df.iterrows():
        route_id = row['ID']
        route_data[route_id] = {
            'Название': row['Маршрут'],
            'Расстояние': row['Расстояние, км.'],
            'Время старта': row['Время старта замера, чч:мм:сек'],
            'Продолжительность': row['Продолжительность поездки, чч:мм:сек.'],
            'Средняя скорость': row['Средняя скорость, км/ч.'],
            'ФИО': row['Ф.И.О.']
        }
    return route_data

# Функция для парсинга одного GPX файла и извлечения координат
def parse_gpx(file_path):
    tree = ET.parse(file_path)
    root = tree.getroot()

    # Пространства имен для корректного парсинга GPX
    namespaces = {
        'gpx': 'http://www.topografix.com/GPX/1/1',
        'geotracker': 'http://ilyabogdanovich.com/gpx/extensions/geotracker'
    }

    # Список для хранения координат точек
    coordinates = []

    # Поиск всех точек <trkpt>
    for trkpt in root.findall('.//gpx:trkpt', namespaces):
        lat = float(trkpt.attrib['lat'])
        lon = float(trkpt.attrib['lon'])
        ele = float(trkpt.find('gpx:ele', namespaces).text)  # Высота (опционально)
        time = trkpt.find('gpx:time', namespaces).text      # Время (опционально)
        coordinates.append((lat, lon))

    return coordinates

# Функция для создания карты с фильтром маршрутов
def create_map_with_filter(all_tracks_data, route_data, api_key):
    # Находим первую точку первого маршрута для центрирования карты
    first_point = None
    for folder_data in all_tracks_data.values():
        if folder_data:  # Если есть треки в этой папке
            first_track_info = folder_data[0]
            if first_track_info['coords']:  # Если у первого трека есть координаты
                first_point = first_track_info['coords'][0]
                break

    if not first_point:
        print("Нет данных с координатами для создания карты.")
        m = folium.Map(location=[55.75, 37.62], zoom_start=10)  # Возвращаем пустую карту с центром в Москве
    else:
        # Создаем карту с центром в первой точке первого маршрута
        m = folium.Map(location=first_point, zoom_start=13)

    # Добавляем слой для каждого индивидуального маршрута (файла)
    for folder_name, folder_data in all_tracks_data.items():
        for track_info in folder_data:
            filename = track_info['filename']
            coordinates = track_info['coords']
            base_filename = os.path.splitext(filename)[0]  # Имя файла без расширения .gpx

            if not coordinates:  # Пропускаем файлы без координат
                print(f"Пропущен файл '{filename}' в папке '{folder_name}' - нет координат.")
                continue

            # Получаем ID маршрута из имени файла
            try:
                route_id = int(base_filename.split('_')[0])  # Предполагаем, что ID маршрута указан в начале имени файла
            except ValueError:
                print(f"Пропущен файл '{filename}' в папке '{folder_name}' - некорректный ID маршрута.")
                continue

            # Получаем информацию о маршруте из route_data
            route_info = route_data.get(route_id, {})
            popup_text = f"""
            <b>Маршрут:</b> {route_info.get('Название', 'Не указано')}<br>
            <b>Расстояние:</b> {route_info.get('Расстояние', 'Не указано')} км<br>
            <b>Время старта:</b> {route_info.get('Время старта', 'Не указано')}<br>
            <b>Продолжительность:</b> {route_info.get('Продолжительность', 'Не указано')}<br>
            <b>Средняя скорость:</b> {route_info.get('Средняя скорость', 'Не указано')} км/ч<br>
            <b>Ответственный:</b> {route_info.get('ФИО', 'Не указано')}
            """

            # Создаем FeatureGroup для каждого трека
            layer_name = f"{folder_name} / {base_filename}"
            track_layer = folium.FeatureGroup(name=layer_name, show=False)

            # Добавляем сам маршрут (линию)
            folium.PolyLine(
                locations=coordinates,
                color='blue',
                weight=4,
                opacity=0.8,
                popup=folium.Popup(popup_text, max_width=300)  # Добавляем Popup с информацией из Excel
            ).add_to(track_layer)

            # Добавляем маркер начала
            folium.Marker(
                location=coordinates[0],
                popup=f"Начало: {base_filename}",
                icon=folium.Icon(color='green', icon='play')
            ).add_to(track_layer)

            # Добавляем маркер конца
            folium.Marker(
                location=coordinates[-1],
                popup=f"Конец: {base_filename}",
                icon=folium.Icon(color='red', icon='stop')
            ).add_to(track_layer)

            # Добавляем слой на карту
            track_layer.add_to(m)

    # Добавляем остановки через Overpass API
    all_coordinates = []
    for folder_data in all_tracks_data.values():
        for track_info in folder_data:
            all_coordinates.extend(track_info['coords'])

    if all_coordinates:
        min_lat = min(coord[0] for coord in all_coordinates)
        max_lat = max(coord[0] for coord in all_coordinates)
        min_lon = min(coord[1] for coord in all_coordinates)
        max_lon = max(coord[1] for coord in all_coordinates)
        bounds = (min_lat, min_lon, max_lat, max_lon)

        bus_stops = fetch_bus_stops(bounds)
        if bus_stops:
            for stop in bus_stops:
                folium.CircleMarker(
                    location=stop,
                    radius=5,
                    color='orange',
                    fill=True,
                    fill_color='orange',
                    fill_opacity=0.7,
                    popup="Остановка общественного транспорта"
                ).add_to(m)

    # Добавляем слой управления для переключения индивидуальных маршрутов
    folium.LayerControl(collapsed=False).add_to(m)

    # Сохраняем карту в HTML файл
    output_dir = "map"
    os.makedirs(output_dir, exist_ok=True)
    output_filename = os.path.join(output_dir, "filtered_tracks_map.html")
    m.save(output_filename)
    print(f"Карта сохранена в файл {output_filename}")
    return m  # Возвращаем объект карты

# Основная программа
if __name__ == "__main__":
    # Путь к директории с GPX файлами
    gpx_directory = "tracks"

    # Ваш API ключ
    yandex_api_key = "d781cefc-4b7d-434b-8531-ddb9b72d33b9"

    # Путь к Excel файлу
    excel_file = "Результаты треков ЛИМБ-21-1.xlsx"

    # Загружаем данные маршрутов
    route_data = load_route_data(excel_file)

    # Получаем список GPX файлов
    gpx_files = [os.path.join(gpx_directory, f) for f in os.listdir(gpx_directory) if f.endswith('.gpx')]

    if not gpx_files:
        print(f"В директории '{gpx_directory}' не найдено ни одного GPX файла.")
    else:
        all_tracks_data = {'tracks': []}
        for gpx_file in gpx_files:
            try:
                coordinates = parse_gpx(gpx_file)
                all_tracks_data['tracks'].append({
                    'filename': os.path.basename(gpx_file),
                    'coords': coordinates
                })
                print(f"Файл '{gpx_file}' успешно обработан. Найдено {len(coordinates)} точек.")
            except Exception as e:
                print(f"Ошибка при обработке файла '{gpx_file}': {e}")

        # Создаем карту
        if all_tracks_data['tracks']:
            create_map_with_filter(all_tracks_data, route_data, yandex_api_key)
