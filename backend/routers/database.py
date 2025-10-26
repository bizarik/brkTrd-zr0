"""Database explorer and query API router"""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query as QueryParam, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, inspect
from sqlalchemy.sql import sqltypes
from pydantic import BaseModel
import structlog
import re

from database import get_db, engine
from models import Base

logger = structlog.get_logger()
router = APIRouter()


class QueryRequest(BaseModel):
    sql: str
    limit: Optional[int] = None  # None = no limit, user controls via SQL


@router.get("/schema")
async def get_database_schema(
    db: AsyncSession = Depends(get_db)
):
    """Get database schema information (tables, columns, types)"""
    try:
        # Get all tables from metadata
        tables_info = []
        
        for table_name, table in Base.metadata.tables.items():
            columns_info = []
            
            for column in table.columns:
                # Get column type as string
                col_type = str(column.type)
                
                columns_info.append({
                    "name": column.name,
                    "type": col_type,
                    "nullable": column.nullable,
                    "primary_key": column.primary_key,
                    "foreign_key": bool(column.foreign_keys)
                })
            
            # Get row count for each table
            try:
                count_query = text(f"SELECT COUNT(*) FROM {table_name}")
                result = await db.execute(count_query)
                count = result.scalar()
            except Exception:
                count = 0
            
            tables_info.append({
                "name": table_name,
                "columns": columns_info,
                "row_count": count,
                "primary_keys": [col.name for col in table.columns if col.primary_key],
                "foreign_keys": [
                    {
                        "column": col.name,
                        "references": f"{list(col.foreign_keys)[0].column.table.name}.{list(col.foreign_keys)[0].column.name}"
                    }
                    for col in table.columns if col.foreign_keys
                ]
            })
        
        return {
            "tables": sorted(tables_info, key=lambda x: x["name"]),
            "total_tables": len(tables_info)
        }
        
    except Exception as e:
        logger.error("schema_fetch_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch schema: {str(e)}")


@router.post("/query")
async def execute_query(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db)
):
    """Execute a read-only SQL query"""
    try:
        sql = request.sql
        
        # Validate query is read-only
        sql_clean = sql.strip().upper()
        
        # Block any write operations
        forbidden_keywords = [
            'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER',
            'TRUNCATE', 'REPLACE', 'MERGE', 'GRANT', 'REVOKE'
        ]
        
        for keyword in forbidden_keywords:
            if re.search(r'\b' + keyword + r'\b', sql_clean):
                raise HTTPException(
                    status_code=400,
                    detail=f"Query contains forbidden keyword: {keyword}. Only SELECT queries are allowed."
                )
        
        # Only add LIMIT if explicitly requested via the limit parameter AND query doesn't have one
        if request.limit is not None and 'LIMIT' not in sql_clean:
            sql = f"{sql.rstrip(';')} LIMIT {request.limit}"
        
        # Execute query
        result = await db.execute(text(sql))
        
        # Fetch results
        rows = result.fetchall()
        
        # Get column names
        columns = list(result.keys()) if rows else []
        
        # Convert to list of dicts
        data = [
            {columns[i]: (str(value) if value is not None else None) for i, value in enumerate(row)}
            for row in rows
        ]
        
        return {
            "success": True,
            "columns": columns,
            "rows": data,
            "row_count": len(data),
            "query": sql
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("query_execution_error", sql=sql, error=str(e), exc_info=True)
        raise HTTPException(
            status_code=400,
            detail=f"Query execution failed: {str(e)}"
        )


@router.get("/tables/{table_name}/preview")
async def preview_table(
    table_name: str,
    limit: int = QueryParam(default=10, le=100),
    db: AsyncSession = Depends(get_db)
):
    """Get a preview of table data"""
    try:
        # Validate table exists in metadata
        if table_name not in Base.metadata.tables:
            raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")
        
        # Execute preview query
        query = text(f"SELECT * FROM {table_name} LIMIT :limit")
        result = await db.execute(query, {"limit": limit})
        
        rows = result.fetchall()
        columns = list(result.keys())
        
        data = [
            {columns[i]: (str(value) if value is not None else None) for i, value in enumerate(row)}
            for row in rows
        ]
        
        return {
            "table": table_name,
            "columns": columns,
            "rows": data,
            "preview_count": len(data)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("table_preview_error", table=table_name, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to preview table: {str(e)}")


@router.get("/stats")
async def get_database_stats(
    db: AsyncSession = Depends(get_db)
):
    """Get overall database statistics"""
    try:
        stats = {}
        
        for table_name in Base.metadata.tables.keys():
            try:
                count_query = text(f"SELECT COUNT(*) FROM {table_name}")
                result = await db.execute(count_query)
                stats[table_name] = result.scalar()
            except Exception:
                stats[table_name] = 0
        
        return {
            "table_counts": stats,
            "total_tables": len(stats),
            "total_rows": sum(stats.values())
        }
        
    except Exception as e:
        logger.error("stats_fetch_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {str(e)}")

