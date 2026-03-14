/**
 * 搜索页面
 */

import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import { Search as SearchIcon, ChevronLeft, ChevronRight, Upload, Download, Zap, Folder, Star, Activity, Clapperboard, Tv } from 'lucide-react';
import { api, type SearchResult } from '../api/client';
import { useToast } from '../components/ToastContext';
import './Search.css';

export function Search() {
    const [keyword, setKeyword] = useState('');
    const [searchTerm, setSearchTerm] = useState('');
    const [category, setCategory] = useState('movie');
    const [page, setPage] = useState(1);
    const [downloadingId, setDownloadingId] = useState<string | null>(null);
    const [activeCategoryMenuId, setActiveCategoryMenuId] = useState<string | null>(null);
    const pageSize = 20;

    const queryClient = useQueryClient();
    const toast = useToast();

    const { data: categories } = useQuery({
        queryKey: ['categories'],
        queryFn: () => api.getCategories(),
    });

    const { data: qbitCategories } = useQuery({
        queryKey: ['qbit-categories'],
        queryFn: () => api.getQbitCategories(),
    });

    const { data: results, isLoading, error } = useQuery({
        queryKey: ['search', searchTerm, category, page],
        queryFn: () => api.search(searchTerm, category, page),
        enabled: searchTerm.length > 0,
    });

    // 计算总页数（M-Team API 只返回当前页数量，假设有更多页）
    const hasMore = results?.results.length === pageSize;

    const downloadMutation = useMutation({
        mutationFn: ({ torrentId, qbitCategory }: { torrentId: string; qbitCategory?: string }) =>
            api.addDownload(torrentId, undefined, qbitCategory),
        onSuccess: () => {
            setDownloadingId(null);
            queryClient.invalidateQueries({ queryKey: ['downloads'] });
            toast.success('下载任务已添加');
        },
        onError: (error: Error) => {
            setDownloadingId(null);
            toast.error(`添加失败: ${error.message}`);
        },
    });

    // Trending Queries
    const { data: trendingMovies } = useQuery({
        queryKey: ['trending', 'movie'],
        queryFn: () => api.getTrending('movie'),
        staleTime: 1000 * 60 * 60, // 1 hour
        enabled: !keyword && !searchTerm,
    });

    const { data: trendingTv } = useQuery({
        queryKey: ['trending', 'tv'],
        queryFn: () => api.getTrending('tv'),
        staleTime: 1000 * 60 * 60, // 1 hour
        enabled: !keyword && !searchTerm,
    });

    const handleSubmit = (e: FormEvent) => {
        e.preventDefault();
        if (keyword.trim()) {
            setActiveCategoryMenuId(null);
            setSearchTerm(keyword.trim());
            setPage(1);  // 重置页码
        }
    };

    const handleDownload = (torrentId: string, qbitCategory?: string) => {
        setActiveCategoryMenuId(null);
        setDownloadingId(torrentId);
        downloadMutation.mutate({ torrentId, qbitCategory });
    };

    const handleTrendingSelect = (title: string) => {
        setActiveCategoryMenuId(null);
        setKeyword(title);
        setSearchTerm(title);
        setPage(1);
    };

    return (
        <div className="search-page">
            <header className="page-header">
                <div className="page-header-main">
                    <h1>资源搜索</h1>
                    <p className="page-subtitle">搜索资源并直接送入下载链路</p>
                </div>
            </header>

            {/* 搜索表单 */}
            <form className="search-form card" onSubmit={handleSubmit}>
                <div className="search-input-group">
                    <input
                        type="text"
                        className="input search-input"
                        placeholder="输入关键词搜索 M-Team 资源..."
                        value={keyword}
                        onChange={(e) => setKeyword(e.target.value)}
                    />
                    <button type="submit" className="btn btn-primary btn-icon" disabled={isLoading}>
                        {isLoading ? <div className="spinner" /> : <><SearchIcon size={20} /> <span>搜索</span></>}
                    </button>
                </div>

                {/* 类别筛选 */}
                {categories && (
                    <div className="category-filters">
                        {Object.entries(categories)
                            .filter(([key]) => key !== 'all')  // 移除"全部"选项
                            .map(([key, name]) => (
                                <button
                                    key={key}
                                    type="button"
                                    className={`tag ${category === key ? 'tag-primary' : ''}`}
                                    onClick={() => {
                                        setActiveCategoryMenuId(null);
                                        setCategory(key);
                                        setPage(1);
                                    }}
                                >
                                    {name}
                                </button>
                            ))}
                    </div>
                )}
            </form>

            {!searchTerm && (
                <>
                    {trendingMovies?.results && trendingMovies.results.length > 0 && (
                        <TrendingRow
                            title="热门电影"
                            icon={<Clapperboard size={20} className="text-primary" />}
                            data={trendingMovies.results}
                            onSelect={handleTrendingSelect}
                        />
                    )}
                    {trendingTv?.results && trendingTv.results.length > 0 && (
                        <TrendingRow
                            title="热门剧集"
                            icon={<Tv size={20} className="text-primary" />}
                            data={trendingTv.results}
                            onSelect={handleTrendingSelect}
                        />
                    )}
                </>
            )}

            {/* 搜索结果 */}
            {searchTerm && (
                <div className="search-results">
                    {error && (
                        <div className="card empty-state">
                            <p className="text-error">搜索失败: {(error as Error).message}</p>
                        </div>
                    )}

                    {isLoading && (
                        <div className="card empty-state">
                            <div className="spinner" />
                            <p>搜索中...</p>
                        </div>
                    )}

                    {!isLoading && results && results.results.length === 0 && (
                        <div className="card empty-state">
                            <SearchIcon size={48} className="empty-state-icon" />
                            <p>未找到相关资源</p>
                        </div>
                    )}

                    <AnimatePresence>
                        {results?.results.map((result, index) => (
                            <motion.div
                                key={result.id}
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0 }}
                                transition={{ delay: index * 0.05, duration: 0.2 }}
                            >
                                <ResultCard
                                    result={result}
                                    onDownload={(qbitCategory) => handleDownload(result.id, qbitCategory)}
                                    isDownloading={downloadingId === result.id}
                                    isCategoryMenuOpen={activeCategoryMenuId === result.id}
                                    onToggleCategoryMenu={() =>
                                        setActiveCategoryMenuId((current) => (current === result.id ? null : result.id))
                                    }
                                    onCloseCategoryMenu={() => {
                                        setActiveCategoryMenuId((current) => (current === result.id ? null : current));
                                    }}
                                    qbitCategories={qbitCategories?.categories}
                                />
                            </motion.div>
                        ))}
                    </AnimatePresence>

                    {/* 分页 */}
                    {results && results.results.length > 0 && (
                        <div className="pagination">
                            <button
                                className="btn btn-secondary btn-icon"
                                disabled={page <= 1}
                                onClick={() => {
                                    setActiveCategoryMenuId(null);
                                    setPage((p) => Math.max(1, p - 1));
                                }}
                            >
                                <ChevronLeft size={20} />
                                <span>上一页</span>
                            </button>
                            <span className="page-info">第 {page} 页</span>
                            <button
                                className="btn btn-secondary btn-icon"
                                disabled={!hasMore}
                                onClick={() => {
                                    setActiveCategoryMenuId(null);
                                    setPage((p) => p + 1);
                                }}
                            >
                                <span>下一页</span>
                                <ChevronRight size={20} />
                            </button>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

type TrendingItem = {
    id: number;
    title: string;
    poster?: string | null;
    release_date?: string;
};

function TrendingRow({ title, icon, data, onSelect }: { title: string, icon: React.ReactNode, data: TrendingItem[], onSelect: (title: string) => void }) {
    if (!data || data.length === 0) return null;

    return (
        <div className="trending-section animate-in fade-in slide-in-from-bottom-4 duration-500">
            <div className="trending-header">
                {icon}
                <h2>{title}</h2>
            </div>
            <div className="trending-scroll-container">
                {data.map((item) => (
                    <motion.div
                        key={item.id}
                        className="card trending-card"
                        whileHover={{ y: -4 }}
                        onClick={() => onSelect(item.title)}
                    >
                        {item.poster ? (
                            <img src={item.poster} alt={item.title} className="poster" loading="lazy" />
                        ) : (
                            <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#888' }}>无海报</div>
                        )}
                        <div className="trending-overlay">
                            <h3 className="trending-title">{item.title}</h3>
                            <span className="trending-year">{item.release_date?.split('-')[0]}</span>
                        </div>
                    </motion.div>
                ))}
            </div>
        </div>
    );
}

function ResultCard({
    result,
    onDownload,
    isDownloading,
    isCategoryMenuOpen,
    onToggleCategoryMenu,
    onCloseCategoryMenu,
    qbitCategories,
}: {
    result: SearchResult;
    onDownload: (qbitCategory?: string) => void;
    isDownloading: boolean;
    isCategoryMenuOpen: boolean;
    onToggleCategoryMenu: () => void;
    onCloseCategoryMenu: () => void;
    qbitCategories?: Record<string, string>;
}) {
    const dropdownRef = useRef<HTMLDivElement | null>(null);

    const hasRating = result.douban_rating || result.imdb_rating;

    useEffect(() => {
        if (!isCategoryMenuOpen) {
            return;
        }

        const handlePointerDown = (event: MouseEvent | TouchEvent) => {
            const target = event.target as Node | null;
            if (dropdownRef.current && target && !dropdownRef.current.contains(target)) {
                onCloseCategoryMenu();
            }
        };

        const handleEscape = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onCloseCategoryMenu();
            }
        };

        document.addEventListener('mousedown', handlePointerDown);
        document.addEventListener('touchstart', handlePointerDown);
        document.addEventListener('keydown', handleEscape);

        return () => {
            document.removeEventListener('mousedown', handlePointerDown);
            document.removeEventListener('touchstart', handlePointerDown);
            document.removeEventListener('keydown', handleEscape);
        };
    }, [isCategoryMenuOpen, onCloseCategoryMenu]);

    return (
        <motion.div
            className={`card result-card ${isCategoryMenuOpen ? 'menu-open' : ''}`}
            whileHover={{ y: -2 }}
            transition={{ duration: 0.15 }}
        >
            <div className="result-content">
                <h3 className="result-title">{result.name}</h3>
                {result.small_descr && (
                    <p className="result-descr">{result.small_descr}</p>
                )}

                {/* 评分信息 */}
                {hasRating && (
                    <div className="result-ratings">
                        {result.douban_rating && (
                            <span className="rating douban">
                                <Activity size={14} className="icon-inline" /> 豆瓣 {result.douban_rating}
                            </span>
                        )}
                        {result.imdb_rating && (
                            <span className="rating imdb">
                                <Star size={14} className="icon-inline" /> IMDb {result.imdb_rating}
                            </span>
                        )}
                    </div>
                )}

                <div className="result-meta">
                    <span className="tag">{result.size}</span>
                    <span className="tag tag-success"><Upload size={14} className="icon-inline" /> {result.seeders}</span>
                    <span className="tag"><Download size={14} className="icon-inline" /> {result.leechers}</span>
                    {result.discount && result.discount !== 'null' && (
                        <span className="tag tag-warning"><Zap size={14} className="icon-inline" /> {result.discount}</span>
                    )}
                    {result.tags?.map((tag) => (
                        <span key={tag} className="tag tag-primary">{tag}</span>
                    ))}
                </div>
            </div>

            <div className="result-actions">
                <div className="download-dropdown" ref={dropdownRef}>
                    <button
                        className="btn btn-primary btn-icon"
                        onClick={() => {
                            if (qbitCategories && Object.keys(qbitCategories).length > 0) {
                                onToggleCategoryMenu();
                            } else {
                                onDownload();
                            }
                        }}
                        disabled={isDownloading}
                    >
                        {isDownloading ? <div className="spinner" /> : <><Download size={18} /> <span>下载</span></>}
                    </button>

                    {isCategoryMenuOpen && qbitCategories && (
                        <div className="dropdown-menu">
                            <button
                                className="dropdown-item"
                                onClick={() => {
                                    onCloseCategoryMenu();
                                    onDownload();
                                }}
                            >
                                <Folder size={16} className="icon-inline" /> 默认路径
                            </button>
                            {Object.keys(qbitCategories).map((key) => (
                                <button
                                    key={key}
                                    className="dropdown-item"
                                    onClick={() => {
                                        onCloseCategoryMenu();
                                        onDownload(key);
                                    }}
                                >
                                    <Folder size={16} className="icon-inline" /> {key}
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </motion.div>
    );
}
