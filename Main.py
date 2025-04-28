import xml.etree.ElementTree as ET
import folium
import os
import pandas as pd
import requests
import math

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
# Функция для создания карты с фильтром маршрутов
def create_map_with_filter(all_tracks_data, route_data, api_key):
    # Находим первую точку первого маршрута для центрирования карты
    first_point = None
    map_center = [55.75, 37.62] # Центр по умолчанию (Москва)
    zoom_start = 10

    # Найдем все координаты для определения центра и границ
    all_coordinates = []
    for folder_data in all_tracks_data.values():
        for track_info in folder_data:
            if track_info['coords']: # Добавляем только если есть координаты
                all_coordinates.extend(track_info['coords'])

    if all_coordinates:
        # Вычисляем центр карты как среднее арифметическое всех точек
        avg_lat = sum(p[0] for p in all_coordinates) / len(all_coordinates)
        avg_lon = sum(p[1] for p in all_coordinates) / len(all_coordinates)
        map_center = [avg_lat, avg_lon]
        zoom_start = 13 # Увеличиваем зум, если есть треки
        first_point = all_coordinates[0] # Используем для проверки ниже, но центрируем по среднему
    else:
        print("Нет данных с координатами для центрирования карты. Используется центр по умолчанию.")

    # Создаем карту
    m = folium.Map(location=map_center, zoom_start=zoom_start, control_scale=True)

    # Добавляем слой для каждого индивидуального маршрута (файла)
    # ... (цикл добавления треков остается таким же, как в вашем коде) ...
    for folder_name, folder_data in all_tracks_data.items():
        for track_info in folder_data:
            filename = track_info['filename']
            coordinates = track_info['coords']
            base_filename = os.path.splitext(filename)[0]

            if not coordinates:
                print(f"Пропущен файл '{filename}' в папке '{folder_name}' - нет координат.")
                continue

            try:
                route_id = int(base_filename.split('_')[0])
            except (ValueError, IndexError): # Добавил IndexError на случай имен без '_'
                print(f"Пропущен файл '{filename}' в папке '{folder_name}' - некорректный ID маршрута или формат имени.")
                continue

            route_info = route_data.get(route_id, {})
            popup_text = f"""
            <b>Маршрут:</b> {route_info.get('Название', 'Не указано')}<br>
            <b>Расстояние:</b> {route_info.get('Расстояние', 'Не указано')} км<br>
            <b>Время старта:</b> {route_info.get('Время старта', 'Не указано')}<br>
            <b>Продолжительность:</b> {route_info.get('Продолжительность', 'Не указано')}<br>
            <b>Средняя скорость:</b> {route_info.get('Средняя скорость', 'Не указано')} км/ч<br>
            <b>Ответственный:</b> {route_info.get('ФИО', 'Не указано')}
            """

            layer_name = f"{folder_name} / {base_filename}"
            track_layer = folium.FeatureGroup(name=layer_name, show=False) # Скрываем по умолчанию

            folium.PolyLine(
                locations=coordinates,
                color='blue',
                weight=4,
                opacity=0.8,
                popup=folium.Popup(popup_text, max_width=300)
            ).add_to(track_layer)

            folium.Marker(
                location=coordinates[0],
                popup=f"Начало: {base_filename}",
                icon=folium.Icon(color='green', icon='play')
            ).add_to(track_layer)

            folium.Marker(
                location=coordinates[-1],
                popup=f"Конец: {base_filename}",
                icon=folium.Icon(color='red', icon='stop')
            ).add_to(track_layer)

            track_layer.add_to(m)


    # --- Начало изменений для расширения области остановок ---
    if all_coordinates:
        # Находим минимальные и максимальные координаты треков
        min_lat = min(coord[0] for coord in all_coordinates)
        max_lat = max(coord[0] for coord in all_coordinates)
        min_lon = min(coord[1] for coord in all_coordinates)
        max_lon = max(coord[1] for coord in all_coordinates)

        # Вычисляем размах (span) координат
        lat_span = max_lat - min_lat
        lon_span = max_lon - min_lon

        # Устанавливаем коэффициент расширения (padding). 0.5 = добавить по 50% с каждой стороны
        # Увеличение линейных размеров в 2 раза -> площадь в 4 раза
        padding_factor = 1
        lat_padding = lat_span * padding_factor
        lon_padding = lon_span * padding_factor

        # Добавляем "безопасный" минимальный запас, чтобы избежать нулевого размаха для одного трека
        min_padding_deg = 0.01 # Примерно 1.1 км
        lat_padding = max(lat_padding, min_padding_deg)
        lon_padding = max(lon_padding, min_padding_deg)


        # Вычисляем новые, расширенные границы
        expanded_min_lat = min_lat - lat_padding
        expanded_max_lat = max_lat + lat_padding
        expanded_min_lon = min_lon - lon_padding
        expanded_max_lon = max_lon + lon_padding

        # Формируем кортеж расширенных границ
        expanded_bounds = (expanded_min_lat, expanded_min_lon, expanded_max_lat, expanded_max_lon)

        print(f"Оригинальные границы треков: lat({min_lat:.4f}, {max_lat:.4f}), lon({min_lon:.4f}, {max_lon:.4f})")
        print(f"Расширенные границы для запроса остановок: lat({expanded_min_lat:.4f}, {expanded_max_lat:.4f}), lon({expanded_min_lon:.4f}, {expanded_max_lon:.4f})")

        # Загружаем остановки в расширенных границах
        bus_stops = fetch_bus_stops(expanded_bounds)

        if bus_stops:
            print(f"Загружено {len(bus_stops)} остановок ОТ.")
            # Создаем отдельный слой для остановок
            stops_layer = folium.FeatureGroup(name="Остановки ОТ", show=True) # Показываем по умолчанию
            for stop_lat, stop_lon in bus_stops:
                folium.CircleMarker(
                    location=(stop_lat, stop_lon),
                    radius=4, # Немного уменьшим радиус для потенциально большего кол-ва точек
                    color='blue', # Изменим цвет для отличия
                    fill=True,
                    fill_color='blue',
                    fill_opacity=0.6,
                    popup="Остановка общественного транспорта"
                ).add_to(stops_layer)
            stops_layer.add_to(m) # Добавляем слой остановок на карту
        else:
            print("Остановки в заданной области не найдены или произошла ошибка загрузки.")
    else:
        print("Нет координатных данных для загрузки остановок.")
    # --- Конец изменений ---

    # Добавляем слой управления (теперь он будет включать и слой остановок)
    folium.LayerControl(
        collapsed=True, # Свернуть по умолчанию, если много слоев
        position='topright'
    ).add_to(m)

    # Сохраняем карту в HTML файл
    output_dir = "map"
    os.makedirs(output_dir, exist_ok=True)
    output_filename = os.path.join(output_dir, "filtered_tracks_map_with_stops.html") # Новое имя файла
    m.save(output_filename)
    print(f"Карта сохранена в файл {output_filename}")
    return m

# --- Основная программа ---
if __name__ == "__main__":
    # Путь к директории с GPX файлами
    gpx_directory = "tracks"  # Укажите путь к папке с GPX файлами

    # Путь к общему Excel-файлу
    excel_file = "Результаты треков ЛИМБ-21-1.xlsx"

    # Ваш API ключ Яндекс Карт (не используется напрямую в этом примере для остановок)
    yandex_api_key = "d781cefc-4b7d-434b-8531-ddb9b72d33b9"

    # --- Модификация структуры обработки файлов ---
    # Загружаем данные о маршрутах из Excel
    if not os.path.isfile(excel_file):
        print(f"Ошибка: Файл '{excel_file}' не найден. Завершение работы.")
        exit()
    route_data = load_route_data(excel_file)

    # Словарь для хранения данных по всем папкам
    all_tracks_data = {}

    # Обработка каждой подпапки (возвращаем структуру как в вашем исходном коде)
    if not os.path.isdir(gpx_directory):
         print(f"Ошибка: Директория '{gpx_directory}' не найдена. Завершение работы.")
         exit()

    subdirectories = [
        d for d in os.listdir(gpx_directory)
        if os.path.isdir(os.path.join(gpx_directory, d))
    ]
    if not subdirectories:
        print(f"В директории '{gpx_directory}' не найдено подпапок с треками. Попробуем найти GPX файлы в самой директории '{gpx_directory}'.")
        # Если нет подпапок, ищем файлы прямо в gpx_directory
        gpx_files = [f for f in os.listdir(gpx_directory) if f.lower().endswith('.gpx')]
        if gpx_files:
            print(f"--- Обработка файлов в '{gpx_directory}':")
            folder_tracks = []
            for gpx_filename in gpx_files:
                 gpx_file_path = os.path.join(gpx_directory, gpx_filename)
                 try:
                    coordinates = parse_gpx(gpx_file_path)
                    if coordinates:
                        folder_tracks.append({
                            'filename': gpx_filename,
                            'coords': coordinates
                        })
                        print(f"  Обработан файл: {gpx_filename} (точек: {len(coordinates)})")
                    else:
                         print(f"  Файл '{gpx_filename}' не содержит координат или произошла ошибка парсинга точек.")
                 except ET.ParseError as e:
                    print(f"  Ошибка XML парсинга в файле {gpx_filename}: {e}. Файл пропущен.")
                 except Exception as e:
                    print(f"  Неизвестная ошибка при обработке файла {gpx_filename}: {e}. Файл пропущен.")
            if folder_tracks:
                 all_tracks_data[os.path.basename(gpx_directory)] = folder_tracks # Используем имя основной папки
        else:
             print(f"В директории '{gpx_directory}' и ее подпапках не найдено GPX файлов. Завершение работы.")
             exit()

    else: # Если подпапки есть
        print(f"Найдены папки: {', '.join(subdirectories)}")
        for directory_name in subdirectories:
            full_path = os.path.join(gpx_directory, directory_name)
            gpx_files = [f for f in os.listdir(full_path) if f.lower().endswith('.gpx')]
            if not gpx_files:
                print(f"--- В папке '{directory_name}' не найдено GPX файлов. Пропускаем.")
                continue
            print(f"--- Обработка папки '{directory_name}':")

            folder_tracks = []
            for gpx_filename in gpx_files:
                gpx_file_path = os.path.join(full_path, gpx_filename)
                try:
                    coordinates = parse_gpx(gpx_file_path)
                    if coordinates:
                        folder_tracks.append({
                            'filename': gpx_filename,
                            'coords': coordinates
                        })
                        print(f"  Обработан файл: {gpx_filename} (точек: {len(coordinates)})")
                    else:
                         print(f"  Файл '{gpx_filename}' не содержит координат или произошла ошибка парсинга точек.")
                except ET.ParseError as e:
                    print(f"  Ошибка XML парсинга в файле {gpx_filename}: {e}. Файл пропущен.")
                except Exception as e:
                    print(f"  Неизвестная ошибка при обработке файла {gpx_filename}: {e}. Файл пропущен.")

            if folder_tracks:
                all_tracks_data[directory_name] = folder_tracks

    # Создаем карту, если есть обработанные данные
    if all_tracks_data:
        print("\nСоздание карты...")
        create_map_with_filter(all_tracks_data, route_data, yandex_api_key)
    else:
        print("\nНет данных треков для построения карты. Карта не создана.")