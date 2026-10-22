"""Application entrypoint instance."""

from intelx.app.factory import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("intelx.app.main:app", host="0.0.0.0", port=8000, reload=True)
