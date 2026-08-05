# test_db_conn.py
import asyncio
import asyncpg
from src.core.config import settings
from src.db.session import CREATE_EVENTS_TABLE_SQL, init_connection
from src.db.event_store import EventStoreRepository

async def main():
    print("🔌 Testing connection to PostgreSQL...")
    print(f"🔗 Database URL: {settings.DATABASE_URL}")
    
    try:
        # 1. Create a temporary pool with Type Codec
        pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL,
            min_size=1,
            max_size=2,
            init=init_connection
        )
        print("✅ Pool created successfully!")
        
        # 2. Acquire a connection and create the table
        async with pool.acquire() as conn:
            print("⏳ Executing table creation DDL...")
            await conn.execute(CREATE_EVENTS_TABLE_SQL)
            print("✅ Table agent_event_log and index checked/created!")
            
            # 3. Test Repository Insertion
            repo = EventStoreRepository(conn)
            print("⏳ Inserting test event...")
            event_id = await repo.insert_event(
                session_id="test-session-999",
                agent_name="db_tester_agent",
                event_type="DB_TEST_SUCCESS",
                payload={"status": "all_systems_go", "version": 2026}
            )
            print(f"✅ Event inserted successfully with ID: {event_id}")
            
            # 4. Test Reading
            print("⏳ Fetching events for session...")
            events = await repo.get_session_events("test-session-999")
            print(f"📋 Fetched {len(events)} events:")
            for e in events:
                print(f"   - Event Type: {e['event_type']}, Payload: {e['payload']}, Timestamp: {e['timestamp']}")
                
        # 5. Clean up
        await pool.close()
        print("🛑 Pool closed. Test successful!")
        
    except Exception as e:
        print(f"❌ Database test failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
