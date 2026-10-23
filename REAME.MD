# Practica_MLOPS

Aplicación de Machine Learning para análisis y predicción agroclimática, con una API desarrollada en Python y FastAPI.

## Características

- API REST para consultar funcionalidades del modelo.
- Modelo de Machine Learning serializado.
- Métricas de evaluación del modelo.
- Gestión de configuración mediante variables de entorno.
- Persistencia y caché según la configuración disponible.

## Requisitos

- Python en una versión compatible con las dependencias del proyecto.
- Git.
- `pip` o `uv`, según el método de instalación elegido.

## Instalación

Clona el repositorio:

```bash
git clone https://github.com/USUARIO/Practica_MLOPS.git
cd Practica_MLOPS
```

Crea un entorno virtual:

```bash
python -m venv .venv
```

Actívalo en Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Instala las dependencias:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Configuración

Copia la plantilla de variables de entorno:

```powershell
Copy-Item .env.example .env
```

Edita `.env` con los valores de tu entorno local. No publiques este archivo ni sus credenciales.

## Ejecución

Desde la raíz del proyecto, si el módulo de entrada es `api/main.py` y expone el objeto ASGI `app`:

```powershell
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Consulta `/docs` para revisar la documentación interactiva de FastAPI, si está habilitada.

## Evaluación

Consulta `models/metricas.json` para revisar las métricas registradas del modelo. Los resultados deben interpretarse según el conjunto de evaluación y el procedimiento de entrenamiento documentados.

## Seguridad

- No almacenar secretos en Git.
- Validar y restringir el acceso a los endpoints administrativos.
- Configurar CORS con los orígenes autorizados para cada entorno.
- Revisar los datos antes de publicarlos.

## Estado del proyecto

Proyecto en desarrollo. La disponibilidad de pruebas automatizadas, contenedores y despliegue continuo depende de su implementación efectiva en el repositorio.

## Licencia

Pendiente de definir.
