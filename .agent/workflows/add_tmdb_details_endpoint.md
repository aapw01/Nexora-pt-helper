---
description: add_tmdb_details_endpoint
---

# Add TMDB Details Endpoint Workflow

This workflow describes the changes made to add a dedicated endpoint for fetching TMDB media details, specifically to support retrieving the number of seasons for TV shows in the frontend.

## 1. Backend API Update (`api/routers/subscriptions.py`)

Added a new endpoint `GET /api/tmdb/details` that accepts `tmdb_id` and `type` (default "tv").

```python
@router.get("/tmdb/details")
async def get_tmdb_details(
    tmdb_id: int = Query(..., description="TMDB ID"),
    type: str = Query("tv", description="类型 (tv/movie)"),
):
    """获取 TMDB 详情"""
    if not app_state.tmdb:
        raise HTTPException(status_code=503, detail="TMDB 客户端未初始化")

    try:
        if type == "tv":
            detail = app_state.tmdb.tv_detail(tmdb_id)
            return {"number_of_seasons": detail.get("number_of_seasons", 0)}
        return {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取详情失败: {str(e)}")
```

## 2. Frontend Client Update (`web/src/api/client.ts`)

Added `getTmdbDetail` method to the `ApiClient` class.

```typescript
async getTmdbDetail(tmdbId: string, type: 'tv' | 'movie'): Promise<{ number_of_seasons?: number }> {
    const params = new URLSearchParams({ tmdb_id: tmdbId, type });
    return this.request(`/api/tmdb/details?${params}`);
}
```

## 3. Frontend Component Update (`web/src/pages/Subscriptions.tsx`)

Modified `AddSubscriptionModal` to:
1.  Trigger a `useQuery` call to `getTmdbDetail` when a TV show is selected.
2.  Use the returned `number_of_seasons` to render a `<select>` dropdown with valid season options (1 to N).
3.  Fallback to a number `<input>` if season data is unavailable.

## 4. Frontend Styling Update (`web/src/pages/Subscriptions.css`)

Added styles for `.select` and updated `.season-filter-input` for a cleaner UI.

```css
.select, .input {
    background-color: var(--color-bg);
    border: 1px solid var(--color-border);
    /* ... other styles ... */
}
```
