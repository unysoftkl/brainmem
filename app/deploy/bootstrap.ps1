@echo off
REM 阶段6 一键启动（Windows，需已安装 Docker Desktop）
REM 用法：双击或在 PowerShell 运行 deploy\bootstrap.ps1
setlocal
echo [1/4] 检查 Docker...
where docker >nul 2>nul || (echo 未找到 docker，请先安装 Docker Desktop && exit /b 1)
echo [2/4] 启动 PostgreSQL16 + pgvector...
docker compose -f "%~dp0docker-compose.yml" up -d db || exit /b 1
echo [3/4] 等待数据库就绪...
:wait
docker exec brainmem-db pg_isready -U brainmem -d brainmem >nul 2>nul && goto ready
timeout /t 3 >nul & goto wait
:ready
echo [4/4] 建 schema 并自检...
set BRAINMEM_PG_DSN=postgresql://brainmem:brainmem@127.0.0.1:5432/brainmem
python -c "import sys;sys.path.insert(0,'src');from brainmem.storage.postgres.db import PostgresStorage as P;p=P();p.init_schema();print('schema ready');p.close()" || exit /b 1
echo.
echo 就绪。连接串: %BRAINMEM_PG_DSN%
echo 下一步： python deploy\migrate_to_pg.py --sqlite ^<your.db^>
endlocal
