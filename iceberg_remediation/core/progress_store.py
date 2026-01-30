"""
SQLite-based progress tracking for resumability.

Tracks completed work items to enable resume after interruption.
"""
import aiosqlite
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class ProgressStore:
    """SQLite-based progress tracking for resumability."""
    
    def __init__(self, db_path: str = "progress.db"):
        """
        Initialize progress store.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
    
    async def initialize(self) -> None:
        """Create tables if they don't exist."""
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS remediation_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                expiry TEXT,
                strike REAL,
                option_type TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(run_id, symbol, trade_date, expiry, strike, option_type)
            )
        """)
        
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS remediation_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                table_name TEXT NOT NULL,
                symbol TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                row_count INTEGER,
                details TEXT,
                created_at TEXT NOT NULL
            )
        """)
        
        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_progress_run_status
            ON remediation_progress(run_id, status)
        """)
        
        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_progress_symbol_date
            ON remediation_progress(symbol, trade_date)
        """)
        
        await self._conn.commit()
        logger.info("progress_store_initialized", db_path=self.db_path)
    
    async def mark_started(
        self,
        run_id: str,
        symbol: str,
        trade_date: date,
        expiry: Optional[date] = None,
        strike: Optional[Decimal] = None,
        option_type: Optional[str] = None,
    ) -> None:
        """Mark a work item as started."""
        now = datetime.now().isoformat()
        
        await self._conn.execute("""
            INSERT INTO remediation_progress 
            (run_id, symbol, trade_date, expiry, strike, option_type, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'in_progress', ?, ?)
            ON CONFLICT(run_id, symbol, trade_date, expiry, strike, option_type) 
            DO UPDATE SET status = 'in_progress', updated_at = ?
        """, (
            run_id, symbol, str(trade_date),
            str(expiry) if expiry else None,
            float(strike) if strike else None,
            option_type,
            now, now, now
        ))
        await self._conn.commit()
    
    async def mark_completed(
        self,
        run_id: str,
        symbol: str,
        trade_date: date,
        expiry: Optional[date] = None,
        strike: Optional[Decimal] = None,
        option_type: Optional[str] = None,
    ) -> None:
        """Mark a work item as completed."""
        now = datetime.now().isoformat()
        
        await self._conn.execute("""
            UPDATE remediation_progress 
            SET status = 'completed', updated_at = ?
            WHERE run_id = ? AND symbol = ? AND trade_date = ?
              AND (expiry IS NULL AND ? IS NULL OR expiry = ?)
              AND (strike IS NULL AND ? IS NULL OR strike = ?)
              AND (option_type IS NULL AND ? IS NULL OR option_type = ?)
        """, (
            now, run_id, symbol, str(trade_date),
            str(expiry) if expiry else None, str(expiry) if expiry else None,
            float(strike) if strike else None, float(strike) if strike else None,
            option_type, option_type
        ))
        await self._conn.commit()
    
    async def mark_failed(
        self,
        run_id: str,
        symbol: str,
        trade_date: date,
        error: str,
        expiry: Optional[date] = None,
        strike: Optional[Decimal] = None,
        option_type: Optional[str] = None,
    ) -> None:
        """Mark a work item as failed."""
        now = datetime.now().isoformat()
        
        await self._conn.execute("""
            UPDATE remediation_progress 
            SET status = 'failed', error_message = ?, updated_at = ?
            WHERE run_id = ? AND symbol = ? AND trade_date = ?
              AND (expiry IS NULL AND ? IS NULL OR expiry = ?)
              AND (strike IS NULL AND ? IS NULL OR strike = ?)
              AND (option_type IS NULL AND ? IS NULL OR option_type = ?)
        """, (
            error, now, run_id, symbol, str(trade_date),
            str(expiry) if expiry else None, str(expiry) if expiry else None,
            float(strike) if strike else None, float(strike) if strike else None,
            option_type, option_type
        ))
        await self._conn.commit()
    
    async def is_completed(
        self,
        run_id: str,
        symbol: str,
        trade_date: date,
        expiry: Optional[date] = None,
        strike: Optional[Decimal] = None,
        option_type: Optional[str] = None,
    ) -> bool:
        """Check if work item is already completed."""
        cursor = await self._conn.execute("""
            SELECT 1 FROM remediation_progress 
            WHERE run_id = ? AND symbol = ? AND trade_date = ?
              AND (expiry IS NULL AND ? IS NULL OR expiry = ?)
              AND (strike IS NULL AND ? IS NULL OR strike = ?)
              AND (option_type IS NULL AND ? IS NULL OR option_type = ?)
              AND status = 'completed'
        """, (
            run_id, symbol, str(trade_date),
            str(expiry) if expiry else None, str(expiry) if expiry else None,
            float(strike) if strike else None, float(strike) if strike else None,
            option_type, option_type
        ))
        row = await cursor.fetchone()
        return row is not None
    
    async def log_audit(
        self,
        run_id: str,
        operation: str,
        table_name: str,
        symbol: str,
        trade_date: date,
        row_count: int,
        details: Optional[str] = None,
    ) -> None:
        """Log an audit entry."""
        now = datetime.now().isoformat()
        
        await self._conn.execute("""
            INSERT INTO remediation_audit 
            (run_id, operation, table_name, symbol, trade_date, row_count, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (run_id, operation, table_name, symbol, str(trade_date), row_count, details, now))
        await self._conn.commit()
    
    async def get_summary(self, run_id: str) -> Dict[str, int]:
        """Get summary of run progress."""
        cursor = await self._conn.execute("""
            SELECT status, COUNT(*) as count
            FROM remediation_progress
            WHERE run_id = ?
            GROUP BY status
        """, (run_id,))
        rows = await cursor.fetchall()
        return {row['status']: row['count'] for row in rows}
    
    async def get_failed_items(self, run_id: str) -> List[Dict]:
        """Get list of failed items for retry."""
        cursor = await self._conn.execute("""
            SELECT symbol, trade_date, expiry, strike, option_type, error_message
            FROM remediation_progress
            WHERE run_id = ? AND status = 'failed'
            ORDER BY trade_date, symbol
        """, (run_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    async def reset_run(self, run_id: str) -> int:
        """Reset all progress for a run (for force restart)."""
        cursor = await self._conn.execute("""
            DELETE FROM remediation_progress WHERE run_id = ?
        """, (run_id,))
        await self._conn.commit()
        return cursor.rowcount
    
    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("progress_store_closed")
