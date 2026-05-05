import asyncio
import os
import traceback

from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    uri = os.environ.get('MONGO_URI', 'mongodb://localhost:27017')
    print('MONGO_URI=', uri)
    try:
        client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
        r = await client.admin.command('ping')
        print('MOTOR PING OK', r)
    except Exception:
        traceback.print_exc()
        raise
    finally:
        try:
            client.close()
        except Exception:
            pass

if __name__ == '__main__':
    asyncio.run(main())
