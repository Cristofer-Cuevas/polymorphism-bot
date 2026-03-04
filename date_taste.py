from datetime import datetime

# Tus strings exactos
fecha_nueva = "2026-02-18 17:00:02.729952+00:00"
fecha_vieja = "2026-02-12 17:00:03.161741+00:00"

print("--- PRUEBA DE TEXTO (STRING) ---")
# Comparación directa de texto
if fecha_nueva > fecha_vieja:
    print(f"✅ Correcto: {fecha_nueva} ES MAYOR QUE {fecha_vieja}")
else:
    print("❌ Error: Algo raro pasa con tus strings.")

print("\n--- PRUEBA DE OBJETO (DATETIME) ---")
# Conversión profesional (Formato con espacio y microsegundos)
formato = "%Y-%m-%d %H:%M:%S.%f%z"

dt_nueva = datetime.strptime(fecha_nueva, formato)
dt_vieja = datetime.strptime(fecha_vieja, formato)

if dt_nueva > dt_vieja:
    print(f"✅ Correcto: El día {dt_nueva.day} es después del día {dt_vieja.day}")
else:
    print("❌ Error de lógica.")