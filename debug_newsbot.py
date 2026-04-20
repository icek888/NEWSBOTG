import asyncio
import sys
sys.path.insert(0, '/app')
from app.database import AsyncSessionLocal
from app.models.base import News, Publication
from sqlalchemy import select

async def test():
    async with AsyncSessionLocal() as session:
        # Check news
        stmt = select(News).order_by(News.created_at.desc()).limit(5)
        res = await session.execute(stmt)
        news_list = res.scalars().all()
        
        print(f"DEBUG: ВСЕГО новостей: {len(news_list)}")
        for n in news_list:
            print(f"DEBUG: ID={n.id}, title={n.title[:60]}, is_published={n.is_published}")
        
        # Check if there are news without Publication
        stmt = (
            select(News)
            .outerjoin(Publication, Publication.news_id == News.id)
            .where(Publication.id.is_(None))
            .where(News.is_published == False)
            .limit(20)
        )
        res = await session.execute(stmt)
        news_no_pub = res.scalars().all()
        
        print(f"DEBUG: Неопубликованных без Publication: {len(news_no_pub)}")
        
        # Try to create Publication
        for n in news_no_pub:
            try:
                pub = Publication(news_id=n.id, status='review_raw')
                session.add(pub)
            except Exception as e:
                print(f"DEBUG: ERROR for news_id={n.id}: {e}")
        
        await session.commit()
        print("DEBUG: Publication created successfully")

asyncio.run(test())
