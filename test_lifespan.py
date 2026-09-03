import asyncio
from src.main import app

async def test_lifespan():
    print("Testing lifespan...")
    try:
        async with app.router.lifespan_context(app):
            print("Lifespan successfully entered.")
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_lifespan())
