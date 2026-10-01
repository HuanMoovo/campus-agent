# PyInstaller specification. Build on Windows x64, invoked by scripts/build_desktop.py.
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata

project = Path(SPECPATH).parent
backend = project / 'backend'
datas = []
hidden = ['uvicorn.logging', 'uvicorn.loops.asyncio', 'uvicorn.protocols.http.h11_impl',
          'uvicorn.lifespan.on', 'sqlalchemy.dialects.sqlite', 'sqlalchemy.dialects.postgresql.psycopg',
          'psycopg', 'psycopg_binary', 'multipart', 'python_multipart', 'pypdf']
for package in ['uvicorn', 'langgraph', 'langchain_core', 'langgraph_sdk']:
    hidden += collect_submodules(package)
    datas += collect_data_files(package)
for package in ['fastapi', 'starlette', 'uvicorn', 'sqlalchemy', 'langgraph', 'langgraph-checkpoint',
                'langgraph-prebuilt', 'langgraph-sdk', 'langchain-core', 'pydantic', 'pydantic-settings',
                'pypdf', 'anyio', 'httpx', 'psycopg', 'psycopg-binary']:
    datas += copy_metadata(package)

full_rag = os.environ.get('CAMPUS_BUNDLE_RAG') == '1'
if full_rag:
    for package in ['chromadb', 'FlagEmbedding', 'sentence_transformers', 'transformers']:
        hidden += collect_submodules(package)
        datas += collect_data_files(package)
    for package in ['chromadb', 'FlagEmbedding', 'sentence-transformers', 'transformers', 'torch']:
        datas += copy_metadata(package)

a = Analysis([str(backend / 'desktop_entry.py')], pathex=[str(backend)], binaries=[], datas=datas,
             hiddenimports=hidden, hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['pytest', 'tkinter', 'matplotlib', 'IPython', 'tensorflow']
                      + ([] if full_rag else ['chromadb', 'FlagEmbedding', 'torch']), noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='campus-backend', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='campus-backend')
