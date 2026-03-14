/**
 * API 客户端
 * 封装与后端 API 的通信
 */

// 使用相对路径，通过 Nginx 代理到后端
// 开发环境可以设置 VITE_API_URL=http://localhost:8000
const API_BASE = import.meta.env.VITE_API_URL || '';

export interface SearchResult {
    id: string;
    name: string;
    small_descr: string;
    size: string;
    size_bytes: number;
    seeders: number;
    leechers: number;
    upload_date: string;
    category: string;
    labels: string[];
    imdb_url: string;
    imdb_rating: string;
    douban_url: string;
    douban_rating: string;
    poster: string;
    discount: string;
    tags: string[];
}

export interface Download {
    hash: string;
    name: string;
    progress: number;
    state_code: string;
    state_text: string;
    // 兼容字段：与 state_text 一致
    state: string;
    size: number;
    downloaded: number;
    uploaded: number;
    dlspeed: number;
    upspeed: number;
    eta: number;
    category: string;
    save_path: string;
}

export interface DownloadsResponse {
    downloads: Download[];
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
}

export interface Subscription {
    id: number;
    tmdb_id: string;
    type: string;
    title: string;
    year: string;
    season_filter: number | null;
    status: 'active' | 'finished';
    status_text: string;
    finished: boolean;
    created_at: number;
    progress: {
        total: number;
        downloaded: number;
        organized: number;
    };
}

export interface SystemStatus {
    mteam: { connected: boolean; message: string };
    qbittorrent: { connected: boolean; version: string | null };
    tmdb: { connected: boolean };
}

// File System types
export interface FileItem {
    name: string;
    path: string;
    is_dir: boolean;
    is_video: boolean;
    size: number;
    mtime: number;
    ext: string;
    error?: string;
}

export interface FsListResponse {
    path: string;
    parent: string | null;
    items: FileItem[];
}

export interface FsStatResponse extends FileItem {
    video_count?: number;
    total_count?: number;
    total_size?: number;
}

export interface FsRoot {
    path: string;
    name: string;
    exists: boolean;
}

export interface OrganizeFileRequest {
    path?: string;  // 单路径（兼容旧版）
    paths?: string[];  // 多路径
    mode: 'copy' | 'move';
    media_type: 'auto' | 'movie' | 'tv';
    dry_run: boolean;
    on_conflict: 'skip' | 'rename' | 'overwrite';
}

export interface OrganizePreviewFile {
    status: string;
    source: string;
    dest?: string;
    dest_dir?: string;
    media_type?: string;
    dry_run?: boolean;
    sidecars?: string[];
    will_scrape?: {
        nfo: string;
        poster?: string;
    };
    reason?: string;
    error?: string;
}

export interface OrganizePreviewResult {
    ok: number;
    skipped: number;
    bad: number;
    total: number;
    dest_dir: string;
    media_type: string;
    files: OrganizePreviewFile[];
}

class ApiClient {
    private baseUrl: string;

    constructor(baseUrl: string) {
        this.baseUrl = baseUrl;
    }

    private async request<T>(endpoint: string, options?: RequestInit): Promise<T> {
        const response = await fetch(`${this.baseUrl}${endpoint}`, {
            headers: {
                'Content-Type': 'application/json',
            },
            ...options,
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        return response.json();
    }

    // Status
    async getStatus(): Promise<SystemStatus> {
        return this.request<SystemStatus>('/api/status');
    }

    // Search
    async getCategories(): Promise<Record<string, string>> {
        return this.request<Record<string, string>>('/api/search/categories');
    }

    async search(
        keyword: string,
        category = 'all',
        page = 1
    ): Promise<{ results: SearchResult[]; page: number; total: number }> {
        const params = new URLSearchParams({
            q: keyword,
            category,
            page: String(page),
        });
        return this.request(`/api/search?${params}`);
    }

    async getTmdbPoster(imdbId: string): Promise<{
        poster: string;
        backdrop: string;
        tmdb_id?: number;
        media_type?: string;
    }> {
        const params = new URLSearchParams({ imdb_id: imdbId });
        return this.request(`/api/tmdb/poster?${params}`);
    }

    // Downloads
    async getDownloads(options?: {
        statusFilter?: string;
        q?: string;
        page?: number;
        pageSize?: number;
        category?: string;
    }): Promise<DownloadsResponse> {
        const params = new URLSearchParams();
        if (options?.statusFilter) params.append('status_filter', options.statusFilter);
        if (options?.q) params.append('q', options.q);
        if (options?.page) params.append('page', String(options.page));
        if (options?.pageSize) params.append('page_size', String(options.pageSize));
        if (options?.category) params.append('category', options.category);
        const queryString = params.toString();
        return this.request(`/api/downloads${queryString ? `?${queryString}` : ''}`);
    }

    async addDownload(torrentId: string, savePath?: string, category?: string) {
        return this.request('/api/downloads', {
            method: 'POST',
            body: JSON.stringify({
                torrent_id: torrentId,
                save_path: savePath,
                category,
            }),
        });
    }

    async manualAddDownload(url: string, category?: string, savePath?: string) {
        return this.request('/api/downloads/manual', {
            method: 'POST',
            body: JSON.stringify({
                url,
                save_path: savePath,
                category,
            }),
        });
    }

    async pauseDownload(hash: string) {
        return this.request(`/api/downloads/${hash}/pause`, { method: 'POST' });
    }

    async resumeDownload(hash: string) {
        return this.request(`/api/downloads/${hash}/resume`, { method: 'POST' });
    }

    async deleteDownload(hash: string, deleteFiles = false) {
        return this.request(`/api/downloads/${hash}?delete_files=${deleteFiles}`, {
            method: 'DELETE',
        });
    }

    async getQbitCategories(): Promise<{ categories: Record<string, string> }> {
        return this.request('/api/qbit/categories');
    }

    async organizeDownloads(hashes: string[]): Promise<{
        success: boolean;
        message: string;
        tasks: { hash: string; task_id: string; name: string }[];
        errors: { hash: string; error: string }[];
    }> {
        return this.request('/api/downloads/organize', {
            method: 'POST',
            body: JSON.stringify({ hashes }),
        });
    }

    // Subscriptions
    async getSubscriptionConfig(): Promise<{
        enabled: boolean;
        interval_minutes: number;
        max_subscriptions: number;
    }> {
        return this.request('/api/subscriptions/config');
    }

    async getSubscriptions(): Promise<{ subscriptions: Subscription[] }> {
        return this.request('/api/subscriptions');
    }

    async addSubscription(tmdbId: string, subType: string, seasonFilter?: number) {
        return this.request('/api/subscriptions', {
            method: 'POST',
            body: JSON.stringify({
                tmdb_id: tmdbId,
                sub_type: subType,
                season_filter: seasonFilter,
            }),
        });
    }

    async deleteSubscription(subId: number) {
        return this.request(`/api/subscriptions/${subId}`, { method: 'DELETE' });
    }

    async getTmdbDetail(tmdbId: string, type: 'tv' | 'movie'): Promise<{ number_of_seasons?: number }> {
        const params = new URLSearchParams({ tmdb_id: tmdbId, type });
        return this.request(`/api/tmdb/details?${params}`);
    }

    async searchTmdb(
        keyword: string,
        type: 'tv' | 'movie'
    ): Promise<{
        results: Array<{
            id: number;
            title: string;
            original_title: string;
            overview: string;
            poster_path: string | null;
            first_air_date: string;
            vote_average: number;
            number_of_seasons?: number | null;
        }>;
        season?: number | null;
        original_query?: string;
        normalized_query?: string;
    }> {
        const params = new URLSearchParams({ q: keyword, type });
        return this.request(`/api/tmdb/search?${params}`);
    }

    async getTrending(type = 'all', timeWindow = 'week'): Promise<{
        results: Array<{
            id: number;
            media_type: 'movie' | 'tv';
            title: string;
            original_title: string;
            overview: string;
            poster: string;
            backdrop: string;
            release_date: string;
            vote_average: number;
        }>;
    }> {
        const params = new URLSearchParams({ type, time_window: timeWindow });
        return this.request(`/api/tmdb/trending?${params}`);
    }

    async refreshSubscription(subId: number): Promise<{
        success: boolean;
        message: string;
        status: 'active' | 'finished';
        status_text: string;
        progress: {
            total: number;
            downloaded: number;
            organized: number;
        };
    }> {
        return this.request(`/api/subscriptions/${subId}/refresh`, { method: 'POST' });
    }

    async refreshAllSubscriptions(): Promise<{
        success: boolean;
        message: string;
    }> {
        return this.request('/api/subscriptions/refresh-all', { method: 'POST' });
    }

    // Organize
    async getOrganizeTasks(
        page: number = 1,
        pageSize: number = 20,
        status?: string,
    ): Promise<{
        tasks: Array<Record<string, unknown>>;
        total: number;
        page: number;
        page_size: number;
        total_pages: number;
    }> {
        const params = new URLSearchParams({
            page: String(page),
            page_size: String(pageSize),
        });
        if (status) {
            params.append('status', status);
        }
        return this.request(`/api/organize/tasks?${params}`);
    }

    async triggerOrganizeScan() {
        return this.request('/api/organize/scan', { method: 'POST' });
    }

    // File System
    async getFsRoots(): Promise<{ roots: FsRoot[] }> {
        return this.request('/api/fs/roots');
    }

    async listDirectory(path?: string): Promise<FsListResponse> {
        const params = path ? new URLSearchParams({ path }) : '';
        return this.request(`/api/fs/list${params ? `?${params}` : ''}`);
    }

    async statPath(path: string): Promise<FsStatResponse> {
        const params = new URLSearchParams({ path });
        return this.request(`/api/fs/stat?${params}`);
    }

    async organizeFiles(request: OrganizeFileRequest): Promise<{
        success: boolean;
        dry_run?: boolean;
        task_id?: string;
        message?: string;
        result?: OrganizePreviewResult;
    }> {
        return this.request('/api/fs/organize', {
            method: 'POST',
            body: JSON.stringify(request),
        });
    }

    async previewOrganize(
        pathOrPaths: string | string[],
        mediaType: 'auto' | 'movie' | 'tv' = 'auto'
    ): Promise<{
        success: boolean;
        dry_run: boolean;
        result: OrganizePreviewResult;
    }> {
        const body: Record<string, unknown> = {
            media_type: mediaType,
            dry_run: true,
            mode: 'move',
            on_conflict: 'skip',
        };
        if (Array.isArray(pathOrPaths)) {
            body.paths = pathOrPaths;
        } else {
            body.path = pathOrPaths;
        }
        return this.request('/api/fs/preview', {
            method: 'POST',
            body: JSON.stringify(body),
        });
    }

    async getLibraries(): Promise<{
        libraries: {
            movie?: string;
            tv?: string;
        };
    }> {
        return this.request('/api/fs/libraries');
    }
}

export const api = new ApiClient(API_BASE);
