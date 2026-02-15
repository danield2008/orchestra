# Aula Virtual (tipo Moodle simple)

Aplicación web en Flask para:

- Iniciar sesión con usuario/contraseña.
- Tener roles (`admin` y `student`).
- Crear cursos.
- Inscribir estudiantes en cursos.
- Subir archivos PDF por curso.
- Permitir que cada estudiante vea solo sus cursos y PDFs.

## Requisitos

- Python 3.10+

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ejecución

```bash
python app.py
```

La app quedará disponible en `http://localhost:5000`.

## Credenciales iniciales

- Usuario: `admin`
- Contraseña: `admin123`

> Cambia estas credenciales al iniciar en producción.

## Estructura

- `app.py`: lógica principal.
- `templates/`: vistas HTML.
- `static/styles.css`: estilos.
- `uploads/`: PDFs subidos.
- `moodle_clone.db`: base SQLite (se crea automáticamente).
