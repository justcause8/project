# -*- coding: utf-8 -*-
import xml.etree.ElementTree as ET
import os
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, TextBox
from math import radians, cos, sin, asin, sqrt
from datetime import datetime, timezone
import requests
try:
    import mplcursors
    MPLCURSORS_AVAILABLE = True
except ImportError:
    MPLCURSORS_AVAILABLE = False
    print("*"*60)
    print("ПРЕДУПРЕЖДЕНИЕ: Библиотека 'mplcursors' не найдена.")
    print("Для интерактивных подсказок установите её: pip install mplcursors")
    print("Интерактивные подсказки будут отключены.")
    print("*"*60)

def haversine(lon1, lat1, lon2, lat2):
    """Рассчитывает расстояние между двумя точками на сфере"""
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    c = 2 * asin(sqrt(a))
    r = 6371  # радиус Земли в км
    return c * r

def is_point_near_osm_stop(lon, lat, osm_stops, threshold_meters=50):
    for stop in osm_stops:
        distance_km = haversine(lon, lat, stop['lon'], stop['lat'])
        if distance_km * 1000 <= threshold_meters:
            return True
    return False

def load_route_data(excel_file):
    try:
        df = pd.read_excel(excel_file)
        route_data = {}
        for _, row in df.iterrows():
            if pd.notna(row['ID']):
                try:
                    route_id = int(row['ID'])
                    route_data[route_id] = {
                        'Название': row.get('Маршрут', 'Не указано'),
                        'Расстояние': row.get('Расстояние, км.', 'Не указано'),
                        'Время старта': row.get('Время старта замера, чч:мм:сек', 'Не указано'),
                        'Продолжительность': row.get('Продолжительность поездки, чч:мм:сек.', 'Не указано'),
                        'Средняя скорость': row.get('Средняя скорость, км/ч.', 'Не указано'),
                        'ФИО': row.get('Ф.И.О.', 'Не указано')
                    }
                except Exception:
                    pass
        return route_data
    except Exception as e:
        print(f"Ошибка при чтении Excel файла '{excel_file}': {e}")
        return {}

def parse_gpx(file_path):
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        namespaces = {'gpx': 'http://www.topografix.com/GPX/1/1'}
        points_data = []
        trkpts = root.findall('.//gpx:trk/gpx:trkseg/gpx:trkpt', namespaces)
        if not trkpts:
            trkpts = root.findall('.//gpx:trkpt', namespaces)
        for trkpt in trkpts:
            try:
                lat = float(trkpt.attrib['lat'])
                lon = float(trkpt.attrib['lon'])
                time_str = trkpt.find('gpx:time', namespaces)
                if time_str is None or not time_str.text:
                    continue
                dt_obj = datetime.fromisoformat(time_str.text.replace('Z', '+00:00'))
                if dt_obj.tzinfo is None:
                    dt_obj = dt_obj.replace(tzinfo=timezone.utc)
                points_data.append((lon, lat, dt_obj))
            except Exception:
                pass
        points_data.sort(key=lambda x: x[2])  # Сортировка по времени
        return points_data
    except Exception as e:
        print(f"Ошибка при парсинге GPX файла '{file_path}': {e}")
        return []

# Запрос остановок
def get_osm_stops(min_lat, min_lon, max_lat, max_lon):
    overpass_url = "http://overpass-api.de/api/interpreter"
    query = f"""
    [out:json][timeout:60];
    (
      node["public_transport"="platform"]({min_lat},{min_lon},{max_lat},{max_lon});
      node["highway"="bus_stop"]({min_lat},{min_lon},{max_lat},{max_lon});
    );
    out center;
    """
    print(f"[OSM] Запрос остановок в области: S={min_lat:.4f}, W={min_lon:.4f}, N={max_lat:.4f}, E={max_lon:.4f}")
    stops = []
    try:
        response = requests.get(overpass_url, params={'data': query})
        response.raise_for_status()
        data = response.json()
        print(f"[OSM] Получено {len(data.get('elements', []))} элементов.")
        for element in data.get('elements', []):
            lat = element.get('lat')
            lon = element.get('lon')
            if lat is None or lon is None:
                center = element.get('center')
                if center:
                    lat = center.get('lat')
                    lon = center.get('lon')
            if lat is not None and lon is not None:
                stops.append({'lat': lat, 'lon': lon})
        print(f"[OSM] Найдено {len(stops)} валидных остановок.")
        return stops
    except requests.exceptions.RequestException as e:
        print(f"[OSM] Ошибка сети при запросе остановок: {e}")
    except Exception as e:
        print(f"[OSM] Неожиданная ошибка при обработке ответа OSM: {e}")
    return []

def plot_tracks_with_stops(all_tracks_data, route_data, uds_path=None):
    fig, ax = plt.subplots(figsize=(12, 10))
    plt.subplots_adjust(left=0.08, right=0.78, top=0.95, bottom=0.1)

    # Переменные для хранения данных
    line_elements_map = {}
    visibility_state = {}
    has_data_to_plot = False
    all_points_exist = False
    min_lat_all, max_lat_all = 90.0, -90.0
    min_lon_all, max_lon_all = 180.0, -180.0
    global_show_osm_stops = True
    osm_stop_marker = None

    # Загрузка дорожной сети из SHP-файла
    if uds_path:
        try:
            # Чтение SHP-файла
            UDS = gpd.read_file(uds_path)
            print("SHP-файл успешно загружен!")
            # Переводим дорожную сеть в проекцию EPSG:4326 (широта/долгота)
            UDS = UDS.to_crs(epsg=4326)
            # Отображаем дорожную сеть
            UDS.plot(ax=ax, edgecolor='grey', facecolor='none', linewidth=0.5, label='Дорожная сеть')
        except Exception as e:
            print(f"Ошибка при чтении SHP-файла: {e}")

    # Поиск границ для всех треков
    if 'tracks' in all_tracks_data:
        for track_info in all_tracks_data['tracks']:
            points_data = track_info['coords']
            if not points_data or len(points_data) < 2:
                continue
            longitudes = [p[0] for p in points_data]
            latitudes = [p[1] for p in points_data]
            min_lat_all = min(min_lat_all, min(latitudes))
            max_lat_all = max(max_lat_all, max(latitudes))
            min_lon_all = min(min_lon_all, min(longitudes))
            max_lon_all = max(max_lon_all, max(longitudes))
            all_points_exist = True

    # Получение OSM остановок
    osm_stops = []
    if all_points_exist:
        margin = 0.01
        osm_stops = get_osm_stops(
            min_lat_all - margin, min_lon_all - margin,
            max_lat_all + margin, max_lon_all + margin
        )

    # Уникальные метки для легенды
    unique_labels_seen = {}

    # Отображение треков и остановок
    if 'tracks' in all_tracks_data:
        for idx, track_info in enumerate(all_tracks_data['tracks']):
            filename = track_info['filename']
            points_data = track_info['coords']
            base_filename = os.path.splitext(filename)[0]

            if not points_data or len(points_data) < 2:
                continue

            longitudes = [p[0] for p in points_data]
            latitudes = [p[1] for p in points_data]
            timestamps = [p[2] for p in points_data]

            # Расчет расстояния и скорости
            total_distance_km = sum(
                haversine(longitudes[i - 1], latitudes[i - 1], longitudes[i], latitudes[i])
                for i in range(1, len(points_data))
            )
            duration_seconds = (timestamps[-1] - timestamps[0]).total_seconds()
            total_time_hours = duration_seconds / 3600.0 if duration_seconds > 0 else 0
            calculated_avg_speed_kmh = total_distance_km / total_time_hours if total_time_hours > 0 else 0.0

            # Создание метки для легенды
            try:
                route_id_str = base_filename.split('_')[0]
                route_id = int(route_id_str)
                route_info_excel = route_data.get(route_id, {})
                plot_label_base = f"{base_filename}"
            except ValueError:
                plot_label_base = base_filename
                route_info_excel = {}

            original_label = plot_label_base
            counter = 1
            while plot_label_base in unique_labels_seen:
                plot_label_base = f"{original_label}_{counter}"
                counter += 1
            unique_labels_seen[plot_label_base] = True

            # Отображение точек маршрута
            ax.plot(longitudes, latitudes, 'bo', markersize=3, label='_nolegend_')

            # Обнаружение остановок
            valid_stop_points_lons = []
            valid_stop_points_lats = []
            confirmed_stop_points_lons = []
            confirmed_stop_points_lats = []
            unconfirmed_stop_points_lons = []
            unconfirmed_stop_points_lats = []

            speed_threshold_kmh = 1
            for i in range(1, len(points_data)):
                prev_lon, prev_lat, prev_time = points_data[i - 1]
                curr_lon, curr_lat, curr_time = points_data[i]
                delta_time_sec = (curr_time - prev_time).total_seconds()

                if delta_time_sec > 1e-6:
                    distance_km = haversine(prev_lon, prev_lat, curr_lon, curr_lat)
                    speed_kmh = (distance_km / delta_time_sec) * 3600.0

                    if speed_kmh < speed_threshold_kmh:
                        valid_stop_points_lons.append(curr_lon)
                        valid_stop_points_lats.append(curr_lat)

                        if is_point_near_osm_stop(curr_lon, curr_lat, osm_stops, threshold_meters=50):
                            confirmed_stop_points_lons.append(curr_lon)
                            confirmed_stop_points_lats.append(curr_lat)
                        else:
                            unconfirmed_stop_points_lons.append(curr_lon)
                            unconfirmed_stop_points_lats.append(curr_lat)

            # Отображение обнаруженных остановок
            if valid_stop_points_lons:
                ax.plot(valid_stop_points_lons, valid_stop_points_lats, 'yo', markersize=8, linestyle='none',
                        label='_nolegend_', picker=5)
            if confirmed_stop_points_lons:
                ax.plot(confirmed_stop_points_lons, confirmed_stop_points_lats, 'go', markersize=6, linestyle='none',
                        label='_nolegend_', picker=5)
            if unconfirmed_stop_points_lons:
                ax.plot(unconfirmed_stop_points_lons, unconfirmed_stop_points_lats, 'ro', markersize=6, linestyle='none',
                        label='_nolegend_', picker=5)

            # Сохранение данных для интерактивности
            line_elements_map[plot_label_base] = {
                'calculated_speed': calculated_avg_speed_kmh,
                'calculated_distance': total_distance_km,
                'coords': points_data
            }
            visibility_state[plot_label_base] = True
            has_data_to_plot = True

    # Проверка наличия данных для отображения
    if not has_data_to_plot:
        print("Нет данных треков для отображения на графике.")
        plt.close(fig)
        return

    # Отображение OSM остановок
    if osm_stops:
        osm_lon = [stop['lon'] for stop in osm_stops]
        osm_lat = [stop['lat'] for stop in osm_stops]
        osm_stop_marker, = ax.plot(osm_lon, osm_lat, 'rs', markersize=5, linestyle='none', label='ОСТАНОВКИ (OSM)', alpha=0.7)
        osm_stop_marker.set_visible(global_show_osm_stops)
    else:
        osm_stop_marker = None

    # Настройка легенды
    simplified_legend_elements = [
        plt.Line2D([0], [0], marker='o', color='b', linestyle='none', label='Маршруты'),
        plt.Line2D([0], [0], marker='s', color='r', linestyle='none', label='Остановки (OSM)'),
        plt.Line2D([0], [0], marker='o', color='y', linestyle='none', label='Обнаруженные остановки'),
        plt.Line2D([0], [0], marker='o', color='g', linestyle='none', label='Подтвержденные остановки'),
        plt.Line2D([0], [0], marker='o', color='r', linestyle='none', label='Неподтвержденные остановки')
    ]

    legend = ax.legend(handles=simplified_legend_elements,
                       bbox_to_anchor=(1.03, 1), loc='upper left',
                       borderaxespad=0., prop={'size': 10},
                       title="Легенда")

    # Кнопка "Скрыть/Показать остановки"
    ax_button_show_hide = fig.add_axes([0.64, 0.015, 0.15, 0.04])
    button_show_hide = Button(ax_button_show_hide, 'Скрыть остановки')

    def toggle_osm_stops(event):
        nonlocal global_show_osm_stops
        if osm_stop_marker is not None:
            global_show_osm_stops = not global_show_osm_stops
            osm_stop_marker.set_visible(global_show_osm_stops)
            button_show_hide.label.set_text('Скрыть остановки' if global_show_osm_stops else 'Показать остановки')
            fig.canvas.draw_idle()

    button_show_hide.on_clicked(toggle_osm_stops)

    # Завершение настройки графика
    ax.set_title("Маршруты с анализом остановок")
    ax.set_xlabel("Долгота")
    ax.set_ylabel("Широта")
    ax.grid(True)

    plt.show()

def haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return 6371 * c  # Расстояние в километрах

# Функция для загрузки данных из CSV
def load_csv_data(csv_file):
    try:
        df = pd.read_csv(csv_file)
        print(f"Данные успешно загружены из файла: {csv_file}")
        return df
    except Exception as e:
        print(f"Ошибка при чтении CSV файла '{csv_file}': {e}")
        return None

# Функция для парсинга данных из CSV
def parse_csv_tracks(df):
    all_tracks_data = {'tracks': []}
    grouped = df.groupby('uuid')
    for uuid, group in grouped:
        points_data = []
        for _, row in group.iterrows():
            if pd.notna(row['lat']) and pd.notna(row['lon']) and pd.notna(row['signal_time']):
                dt_obj = pd.to_datetime(row['signal_time'])
                points_data.append((row['lon'], row['lat'], dt_obj))
        if points_data:
            points_data.sort(key=lambda x: x[2])  # Сортировка по времени
            all_tracks_data['tracks'].append({
                'filename': f"UUID_{uuid}",
                'coords': points_data
            })
    return all_tracks_data


# Основная функция для построения графиков
if __name__ == "__main__":
    csv_file = "normalized_tracks_december.csv"  # Путь к CSV-файлу
    uds_path = 'Graph_Irkutsk_link/Graph_Irkutsk_link.SHP'  # Путь к SHP-файлу

    # Загрузка данных из CSV
    df = load_csv_data(csv_file)
    if df is None:
        exit()

    # Парсинг данных из CSV
    all_tracks_data = parse_csv_tracks(df)

    # Если данные треков найдены, строим график
    if all_tracks_data['tracks']:
        plot_tracks_with_stops(all_tracks_data, route_data={}, uds_path=uds_path)
    else:
        print("Нет данных треков для отображения после обработки CSV файла.")



# from datetime import datetime
# import geopandas as gpd
# import pandas as pd
# import numpy as np
# import os
# import traceback
# from math import radians, cos, sin, asin, sqrt
# import requests
# import matplotlib.pyplot as plt
# from matplotlib.widgets import TextBox, Button
#
# # === Загрузка дорожной сети ===
# def load_road_network(path):
#     """Загружает дорожную сеть из SHP-файла и перепроецирует в EPSG:3857."""
#     if not os.path.exists(path):
#         print(f"Ошибка: Файл дорожной сети не найден: {path}")
#         return None
#     try:
#         roads = gpd.read_file(path)
#         print("Дорожная сеть загружена!")
#         if roads.crs is None:
#             print("Внимание: У SHP-файла отсутствует система координат. Попытка установить WGS84 (EPSG:4326).")
#             roads.set_crs(epsg=4326, inplace=True)
#         return roads.to_crs(epsg=3857)
#     except Exception as e:
#         print(f"Ошибка при чтении SHP-файла или установке/трансформации CRS: {e}")
#         return None
#
# # === Расчет расстояния между точками (Haversine) ===
# def haversine(lon1, lat1, lon2, lat2):
#     """Рассчитывает расстояние между двумя точками на сфере."""
#     lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
#     dlon = lon2 - lon1
#     dlat = lat2 - lat1
#     a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
#     c = 2 * asin(sqrt(a))
#     return 6371 * c  # Расстояние в километрах
#
# # === Проверка близости точки к остановке OSM ===
# def is_point_near_osm_stop(lon, lat, osm_stops, threshold_meters=50):
#     """Проверяет, находится ли точка рядом с остановкой OSM."""
#     for stop in osm_stops:
#         distance_km = haversine(lon, lat, stop['lon'], stop['lat'])
#         if distance_km * 1000 <= threshold_meters:
#             return True
#     return False
#
# # === Получение остановок OSM через API ===
# # === Получение остановок OSM через API ===
# def get_osm_stops(min_lat, min_lon, max_lat, max_lon):
#     """Запрашивает остановки OSM в заданной области."""
#     overpass_url = "http://overpass-api.de/api/interpreter"
#     query = f"""
#     [out:json][timeout:60];
#     (
#       node["public_transport"="platform"]({min_lat},{min_lon},{max_lat},{max_lon});
#       node["highway"="bus_stop"]({min_lat},{min_lon},{max_lat},{max_lon});
#     );
#     out center;
#     """
#     print(f"[OSM] Запрос остановок в области: S={min_lat:.4f}, W={min_lon:.4f}, N={max_lat:.4f}, E={max_lon:.4f}")
#     stops = []
#     try:
#         response = requests.get(overpass_url, params={'data': query})
#         response.raise_for_status()
#         data = response.json()
#         print(f"[OSM] Получено {len(data.get('elements', []))} элементов.")
#         for element in data.get('elements', []):
#             lat = element.get('lat')
#             lon = element.get('lon')
#             if lat is None or lon is None:
#                 center = element.get('center')
#                 if center:
#                     lat = center.get('lat')
#                     lon = center.get('lon')
#             if lat is not None and lon is not None:
#                 stops.append({'lat': lat, 'lon': lon})
#         print(f"[OSM] Найдено {len(stops)} валидных остановок.")
#         return stops
#     except requests.exceptions.RequestException as e:
#         print(f"[OSM] Ошибка сети при запросе остановок: {e}")
#     except Exception as e:
#         print(f"[OSM] Неожиданная ошибка при обработке ответа OSM: {e}")
#     return []
#
# # === Загрузка и обработка данных треков ===
# def load_and_process_tracks(filepath, time_col, time_format, lat_col='lat', lon_col='lon', speed_col='speed', target_crs=None):
#     """Загружает CSV, обрабатывает время, координаты, скорость и создает GeoDataFrame."""
#     if not os.path.exists(filepath):
#         print(f"Предупреждение: Файл треков не найден: {filepath}. Пропуск.")
#         return None
#     print(f"Загрузка треков из {filepath}...")
#     try:
#         tracks_raw = pd.read_csv(filepath, low_memory=False)
#         required_cols = [time_col, lat_col, lon_col, speed_col]
#         missing_cols = [col for col in required_cols if col not in tracks_raw.columns]
#         if missing_cols:
#             print(f"Ошибка в {filepath}: Отсутствуют необходимые столбцы: {', '.join(missing_cols)}")
#             return None
#
#         tracks_raw['speed_num'] = pd.to_numeric(tracks_raw[speed_col], errors='coerce')
#         if time_format:
#             print(f"  Используется формат времени: '{time_format}'")
#             tracks_raw['datetime_col'] = pd.to_datetime(tracks_raw[time_col], format=time_format, errors='coerce')
#         else:
#             print("  Попытка автоопределения формата времени...")
#             tracks_raw['datetime_col'] = pd.to_datetime(tracks_raw[time_col], errors='coerce')
#
#         tracks_raw[lat_col] = pd.to_numeric(tracks_raw[lat_col], errors='coerce')
#         tracks_raw[lon_col] = pd.to_numeric(tracks_raw[lon_col], errors='coerce')
#
#         initial_rows = len(tracks_raw)
#         tracks = tracks_raw.dropna(subset=['datetime_col', lat_col, lon_col, 'speed_num'])
#         dropped_rows = initial_rows - len(tracks)
#         if dropped_rows > 0:
#             print(f"В {filepath} удалено {dropped_rows} строк из-за неверного формата/отсутствия времени, координат или скорости.")
#         if tracks.empty:
#             print(f"В {filepath} не осталось валидных данных после обработки.")
#             return None
#
#         geometry = gpd.points_from_xy(tracks[lon_col], tracks[lat_col])
#         tracks_gdf = gpd.GeoDataFrame(tracks, geometry=geometry, crs='EPSG:4326')
#         if target_crs:
#             tracks_gdf = tracks_gdf.to_crs(target_crs)
#         print(f"Треки из {filepath} загружены и подготовлены.")
#         return tracks_gdf
#     except Exception as e:
#         print(f"Ошибка при загрузке или обработке треков из {filepath}: {e}")
#         traceback.print_exc()
#         return None
#
# # === Извлечение точек с нулевой скоростью ===
# def extract_zero_speed_points(tracks_gdf):
#     """Извлекает точки с нулевой скоростью из GeoDataFrame."""
#     if tracks_gdf is None or tracks_gdf.empty:
#         print("Нет данных для извлечения точек с нулевой скоростью.")
#         return None
#     zero_speed_points = tracks_gdf[tracks_gdf['speed_num'] == 0].copy()
#     if zero_speed_points.empty:
#         print("Нет точек с нулевой скоростью.")
#         return None
#     print(f"Извлечено {len(zero_speed_points)} точек с нулевой скоростью.")
#     return zero_speed_points
#
# # === Подтверждение остановок с помощью OSM ===
# def confirm_stops_with_osm(zero_speed_points, osm_stops, threshold_meters=50):
#     """Подтверждает остановки, находящиеся рядом с остановками OSM."""
#     confirmed_stops = []
#     unconfirmed_stops = []
#     for _, row in zero_speed_points.iterrows():
#         lon, lat = row.geometry.x, row.geometry.y
#         if is_point_near_osm_stop(lon, lat, osm_stops, threshold_meters):
#             confirmed_stops.append(row)
#         else:
#             unconfirmed_stops.append(row)
#     confirmed_stops_gdf = gpd.GeoDataFrame(confirmed_stops, crs=zero_speed_points.crs) if confirmed_stops else None
#     unconfirmed_stops_gdf = gpd.GeoDataFrame(unconfirmed_stops, crs=zero_speed_points.crs) if unconfirmed_stops else None
#     return confirmed_stops_gdf, unconfirmed_stops_gdf
#
# # === Основной блок ===
# if __name__ == "__main__":
#     # --- Пути к файлам ---
#     road_path = "Graph_Irkutsk_link/Graph_Irkutsk_link.SHP"
#     december_tracks_path = "normalized_tracks_december.csv"
#     march_tracks_path = "normalized_tracks_march.csv"
#
#     # --- Имена ключевых столбцов ---
#     time_column = 'signal_time'
#     lat_column = 'lat'
#     lon_column = 'lon'
#     speed_column = 'speed'
#
#     # --- Форматы времени для каждого файла ---
#     december_time_format = '%Y-%m-%d %H:%M:%S'  # Примерный формат для декабря
#     march_time_format = '%H:%M:%S'              # Формат только времени для марта
#
#     # Загрузка дорожной сети
#     roads_gdf = load_road_network(road_path)
#     if roads_gdf is None:
#         exit()
#
#     # Загрузка и обработка треков с указанием формата времени
#     december_tracks_gdf = load_and_process_tracks(
#         december_tracks_path, time_column, december_time_format,
#         lat_column, lon_column, speed_column, roads_gdf.crs
#     )
#     march_tracks_gdf = load_and_process_tracks(
#         march_tracks_path, time_column, march_time_format,
#         lat_column, lon_column, speed_column, roads_gdf.crs
#     )
#
#     # Извлечение точек с нулевой скоростью
#     december_zero_speed_points = extract_zero_speed_points(december_tracks_gdf)
#     march_zero_speed_points = extract_zero_speed_points(march_tracks_gdf)
#
#     # Получение остановок OSM
#     if december_zero_speed_points is not None and not december_zero_speed_points.empty:
#         min_lat = december_zero_speed_points.geometry.y.min()
#         min_lon = december_zero_speed_points.geometry.x.min()
#         max_lat = december_zero_speed_points.geometry.y.max()
#         max_lon = december_zero_speed_points.geometry.x.max()
#         osm_stops = get_osm_stops(min_lat, min_lon, max_lat, max_lon)
#     else:
#         osm_stops = []
#
#     # Подтверждение остановок с помощью OSM
#     if december_zero_speed_points is not None:
#         december_confirmed, december_unconfirmed = confirm_stops_with_osm(december_zero_speed_points, osm_stops)
#     else:
#         december_confirmed, december_unconfirmed = None, None
#
#     if march_zero_speed_points is not None:
#         march_confirmed, march_unconfirmed = confirm_stops_with_osm(march_zero_speed_points, osm_stops)
#     else:
#         march_confirmed, march_unconfirmed = None, None
#
#     # === ВИЗУАЛИЗАЦИЯ ===
#     fig, ax = plt.subplots(figsize=(15, 10))
#     plt.subplots_adjust(left=0.05, right=0.95, top=0.95, bottom=0.25)
#
#     # Рисуем дороги
#     roads_gdf.plot(ax=ax, edgecolor='gray', linewidth=0.5, label='Дорожная сеть', zorder=1)
#
#     # Отображение остановок
#     def plot_stops(ax, stops_gdf, color, marker, label):
#         if stops_gdf is not None and not stops_gdf.empty:
#             ax.scatter(
#                 stops_gdf.geometry.x, stops_gdf.geometry.y,
#                 color=color, marker=marker, s=60, label=label, zorder=5
#             )
#
#     plot_stops(ax, december_confirmed, 'green', 'x', 'Подтвержденные остановки (Декабрь)')
#     plot_stops(ax, december_unconfirmed, 'red', 'x', 'Неподтвержденные остановки (Декабрь)')
#     plot_stops(ax, march_confirmed, 'green', '+', 'Подтвержденные остановки (Март)')
#     plot_stops(ax, march_unconfirmed, 'blue', '+', 'Неподтвержденные остановки (Март)')
#
#     # Отображение OSM-остановок
#     if osm_stops:
#         osm_lon = [stop['lon'] for stop in osm_stops]
#         osm_lat = [stop['lat'] for stop in osm_stops]
#         ax.scatter(osm_lon, osm_lat, color='orange', marker='s', s=50, label='Остановки (OSM)', alpha=0.7)
#
#     # Легенда
#     ax.legend(loc='upper left')
#
#     # Интерактивные элементы
#     start_time_box_ax = plt.axes([0.10, 0.15, 0.30, 0.04])
#     end_time_box_ax = plt.axes([0.10, 0.10, 0.30, 0.04])
#     filter_button_ax = plt.axes([0.10, 0.05, 0.25, 0.04])
#
#     start_time_initial = "00:00:00"
#     end_time_initial = "23:59:59"
#     start_time_box = TextBox(start_time_box_ax, "Начало (ЧЧ:ММ:СС):", initial=start_time_initial)
#     end_time_box = TextBox(end_time_box_ax, "Конец (ЧЧ:ММ:СС):", initial=end_time_initial)
#     filter_button = Button(filter_button_ax, 'Фильтр времени')
#
#     def update_plots_visibility(event=None):
#         """Обновляет видимость меток ОБОИХ наборов данных и применяет фильтр времени суток."""
#         start_time_str = start_time_box.text
#         end_time_str = end_time_box.text
#         try:
#             start_time = pd.to_datetime(start_time_str, format='%H:%M:%S', errors='raise').time()
#             end_time = pd.to_datetime(end_time_str, format='%H:%M:%S', errors='raise').time()
#         except ValueError:
#             start_time = datetime.time(0, 0, 0)
#             end_time = datetime.time(23, 59, 59)
#
#         # Фильтрация и обновление
#         def filter_and_plot(stops_gdf, color, marker, label):
#             if stops_gdf is None or stops_gdf.empty:
#                 return
#             times_in_data = stops_gdf['datetime_col'].dt.time
#             if start_time <= end_time:
#                 time_condition = (times_in_data >= start_time) & (times_in_data <= end_time)
#             else:
#                 time_condition = (times_in_data >= start_time) | (times_in_data <= end_time)
#             filtered_stops = stops_gdf[time_condition]
#             if not filtered_stops.empty:
#                 ax.scatter(
#                     filtered_stops.geometry.x, filtered_stops.geometry.y,
#                     color=color, marker=marker, s=60, label=label, zorder=5
#                 )
#
#         ax.clear()
#         roads_gdf.plot(ax=ax, edgecolor='gray', linewidth=0.5, label='Дорожная сеть', zorder=1)
#
#         filter_and_plot(december_confirmed, 'green', 'x', 'Подтвержденные остановки (Декабрь)')
#         filter_and_plot(december_unconfirmed, 'red', 'x', 'Неподтвержденные остановки (Декабрь)')
#         filter_and_plot(march_confirmed, 'green', '+', 'Подтвержденные остановки (Март)')
#         filter_and_plot(march_unconfirmed, 'blue', '+', 'Неподтвержденные остановки (Март)')
#
#         if osm_stops:
#             osm_lon = [stop['lon'] for stop in osm_stops]
#             osm_lat = [stop['lat'] for stop in osm_stops]
#             ax.scatter(osm_lon, osm_lat, color='orange', marker='s', s=50, label='Остановки (OSM)', alpha=0.7)
#
#         ax.legend(loc='upper left')
#         plt.draw()
#
#     filter_button.on_clicked(update_plots_visibility)
#
#     # Завершение настройки графика
#     ax.set_title("Остановки транспорта по дорожной сети Иркутска")
#     ax.axis('off')
#     plt.show()