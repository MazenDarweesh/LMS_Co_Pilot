import asyncio
import structlog
from src.core.config import settings
from src.models.search_models import SearchRequest
from src.services.search_service import search_service
from src.services.embedding_service import embedding_service
from src.services.qdrant_service import qdrant_service
from src.services.reranker_service import reranker_service
from google import genai

async def main():
    print('Initializing services...')
    await embedding_service.initialize()
    await reranker_service.initialize()
    await qdrant_service.initialize()
    search_service.initialize()
    
    req = SearchRequest(query='ما هو بدء التشغيل وانتهاء التشغيل؟', scope='all', limit=3)
    user_entities = ['tenant:default_company', 'role:Admin', 'role:Student']
    
    print('Calling search...')
    try:
        res = await search_service.search(req, user_entities)
        print('Answer:', res.answer)
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(main())
