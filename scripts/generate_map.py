import pandas as pd
import folium
import branca.colormap as cm
import math

# ================= Configuration =================
INPUT_FILE = 'coalesced_bandwidth_traces.csv'
OUTPUT_FILE = '5g_dots_map.html'
METRIC_COL = 'Downlink Avg(Mbps)'

MIN_DISTANCE_METERS = 5 
# ===============================================

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees)
    """
    R = 6371000 # Radius of earth in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c

print(f"Loading data from {INPUT_FILE}...")
try:
    df = pd.read_csv(INPUT_FILE)
except FileNotFoundError:
    print(f"Error: {INPUT_FILE} not found.")
    exit()

# 1. Data Cleaning
try:
    df['datetime'] = pd.to_datetime(df['Timestamp'], format='%Y.%m.%d_%H.%M.%S.%f')
except:
    df['datetime'] = pd.to_datetime(df['Timestamp'], errors='coerce')

df = df[
    (df['Latitude_NSG'] != 0) & 
    (df['Longitude_NSG'] != 0) & 
    (df['Latitude_NSG'].notnull())
].dropna(subset=['datetime']).sort_values('datetime')

# 2. Spatial Downsampling (The Logic You Asked For)
print(f"Filtering points closer than {MIN_DISTANCE_METERS} meters...")

filtered_data = []
last_lat = None
last_lon = None

raw_count = len(df)

for _, row in df.iterrows():
    lat = row['Latitude_NSG']
    lon = row['Longitude_NSG']
    val = row.get(METRIC_COL, 0)
    
    # Always keep the first point
    if last_lat is None:
        filtered_data.append((lat, lon, val, row['datetime']))
        last_lat, last_lon = lat, lon
        continue
        
    # Calculate distance
    dist = haversine_distance(last_lat, last_lon, lat, lon)
    
    # Only keep if distance is large enough
    if dist >= MIN_DISTANCE_METERS:
        filtered_data.append((lat, lon, val, row['datetime']))
        last_lat, last_lon = lat, lon

print(f"Reduced data points from {raw_count} to {len(filtered_data)}.")

if not filtered_data:
    print("No data points left after filtering.")
    exit()

# 3. Create Map
# Extract lats/lons for centering
lats = [x[0] for x in filtered_data]
lons = [x[1] for x in filtered_data]
avg_lat = sum(lats) / len(lats)
avg_lon = sum(lons) / len(lons)

m = folium.Map(location=[avg_lat, avg_lon], zoom_start=14, tiles='CartoDB positron')

# 4. Color Scale
vals = [x[2] for x in filtered_data]
min_val, max_val = min(vals), max(vals)

colormap = cm.LinearColormap(
    colors=['red', 'orange', 'yellow', 'green'],
    index=[min_val, min_val + (max_val-min_val)*0.33, min_val + (max_val-min_val)*0.66, max_val],
    vmin=min_val,
    vmax=max_val,
    caption=f'{METRIC_COL} (Red=Low, Green=High)'
)
colormap.add_to(m)

# 5. Plot Dots
for lat, lon, val, time in filtered_data:
    color = colormap(val)
    
    folium.CircleMarker(
        location=[lat, lon],
        radius=5,           
        color=color,        
        fill=True,
        fill_color=color,   
        fill_opacity=0.8,
        popup=f"Time: {time}<br>Speed: {val:.2f} Mbps",
        tooltip=f"{val:.0f} Mbps"
    ).add_to(m)

# 6. Save
m.save(OUTPUT_FILE)
print(f"Map generated: {OUTPUT_FILE}")