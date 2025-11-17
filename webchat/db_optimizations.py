"""Database optimization utilities and index management."""
import logging
from typing import List, Dict, Any

from db_utils import get_db_all, get_db_row

logger = logging.getLogger(__name__)


async def ensure_indexes() -> None:
    """Ensure critical indexes exist for performance."""
    
    indexes_to_check = [
        {
            "table": "events_slots",
            "index": "idx_sender_key",
            "columns": ["sender_id", "key2find"],
            "create_sql": """
                CREATE INDEX idx_sender_key ON events_slots(sender_id, key2find)
            """
        },
        {
            "table": "events_slots",
            "index": "idx_sender",
            "columns": ["sender_id"],
            "create_sql": """
                CREATE INDEX idx_sender ON events_slots(sender_id)
            """
        },
    ]
    
    for index_info in indexes_to_check:
        try:
            # Check if index exists
            result = await get_db_row(
                """SELECT COUNT(1) as cnt FROM information_schema.statistics 
                   WHERE table_schema = DATABASE() 
                   AND table_name = %s 
                   AND index_name = %s""",
                [index_info["table"], index_info["index"]]
            )
            
            if result and result.get("cnt", 0) == 0:
                logger.info(f"Creating index {index_info['index']} on {index_info['table']}")
                # Index doesn't exist, create it (for safety, only log recommendation)
                logger.warning(
                    f"RECOMMENDED: Run this SQL to improve performance:\n{index_info['create_sql']}"
                )
            else:
                logger.debug(f"Index {index_info['index']} exists on {index_info['table']}")
                
        except Exception as exc:
            logger.error(f"Error checking index {index_info['index']}: {exc}")


async def get_table_stats() -> Dict[str, Any]:
    """Get statistics about database usage for monitoring."""
    try:
        # Check events_slots table size
        slots_stats = await get_db_row(
            """SELECT 
                COUNT(*) as total_rows,
                COUNT(DISTINCT sender_id) as unique_users
               FROM events_slots"""
        )
        
        return {
            "events_slots": slots_stats or {},
        }
    except Exception as exc:
        logger.error(f"Error getting table stats: {exc}")
        return {}
