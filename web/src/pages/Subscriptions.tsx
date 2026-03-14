import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Plus, Trash2, Tv, Clapperboard, Search, Loader2, X,
    Check, HardDrive, CheckCircle2, AlertCircle, RefreshCw, Clock
} from 'lucide-react';
import { api, type Subscription } from '../api/client';
import { useToast } from '../components/ToastContext';
import './Subscriptions.css';

export function Subscriptions() {
    const [isAddModalOpen, setIsAddModalOpen] = useState(false);
    const queryClient = useQueryClient();
    const toast = useToast();

    const { data, isLoading, error } = useQuery({
        queryKey: ['subscriptions'],
        queryFn: () => api.getSubscriptions(),
    });

    const deleteMutation = useMutation({
        mutationFn: (subId: number) => api.deleteSubscription(subId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['subscriptions'] });
            toast.success('订阅已删除');
        },
        onError: (err: Error) => toast.error(`删除失败: ${err.message}`),
    });

    const refreshAllMutation = useMutation({
        mutationFn: () => api.refreshAllSubscriptions(),
        onSuccess: () => {
            toast.success('已启动后台刷新任务，请稍后刷新页面查看结果');
            // 延迟刷新列表，给后台任务一些时间
            setTimeout(() => {
                queryClient.invalidateQueries({ queryKey: ['subscriptions'] });
            }, 2000);
        },
        onError: (err: Error) => toast.error(`刷新失败: ${err.message}`),
    });

    const { data: config } = useQuery({
        queryKey: ['subscription-config'],
        queryFn: () => api.getSubscriptionConfig(),
    });

    const subscriptions = data?.subscriptions || [];
    const activeCount = subscriptions.filter((s) => s.status !== 'finished').length;

    return (
        <div className="subscriptions-page">
            <header className="page-header">
                <div className="page-header-main">
                    <h1>订阅管理</h1>
                    <p className="page-subtitle">让新内容按规则持续进入媒体库</p>
                    {!isLoading && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span className="text-secondary">
                                {activeCount} 个活跃订阅
                            </span>
                            {config && (
                                <span
                                    className={`tag ${config.enabled ? 'tag-success' : 'tag-secondary'} tag-with-icon`}
                                    title={config.enabled ? `每 ${config.interval_minutes} 分钟自动更新` : '自动更新已禁用'}
                                    style={{ fontSize: '12px' }}
                                >
                                    <Clock size={12} />
                                    {config.enabled ? `自动更新: ${config.interval_minutes}m` : '自动更新已禁用'}
                                </span>
                            )}
                        </div>
                    )}
                </div>
                <div style={{ display: 'flex', gap: 'var(--spacing-sm)' }}>
                    <button
                        className="btn btn-secondary btn-icon"
                        onClick={() => refreshAllMutation.mutate()}
                        disabled={refreshAllMutation.isPending}
                        title="刷新所有订阅的本地文件状态"
                    >
                        {refreshAllMutation.isPending ? <Loader2 size={18} className="animate-spin" /> : <RefreshCw size={18} />}
                        刷新全部
                    </button>
                    <button className="btn btn-primary btn-icon" onClick={() => setIsAddModalOpen(true)}>
                        <Plus size={18} /> 添加订阅
                    </button>
                </div>
            </header>

            {/* 订阅列表 */}
            <div className="subscriptions-list">
                {isLoading && (
                    <div className="card empty-state">
                        <div className="spinner" />
                        <p>加载中...</p>
                    </div>
                )}

                {error && (
                    <div className="card empty-state">
                        <AlertCircle size={48} className="empty-state-icon text-error" />
                        <p className="text-error">加载失败: {(error as Error).message}</p>
                    </div>
                )}

                {!isLoading && subscriptions.length === 0 && (
                    <div className="card empty-state">
                        <Tv size={48} className="empty-state-icon" />
                        <p>暂无订阅</p>
                        <p className="text-sm text-secondary">
                            点击右上角按钮添加订阅
                        </p>
                    </div>
                )}

                <AnimatePresence>
                    {subscriptions.map((sub) => (
                        <motion.div
                            key={sub.id}
                            initial={{ opacity: 0, y: 20 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, x: -20 }}
                            layout
                        >
                            <SubscriptionCard
                                subscription={sub}
                                onDelete={() => {
                                    if (confirm(`确定删除订阅 "${sub.title}"？`)) {
                                        deleteMutation.mutate(sub.id);
                                    }
                                }}
                                onRefresh={() => {
                                    // 刷新单个订阅
                                    api.refreshSubscription(sub.id).then(() => {
                                        queryClient.invalidateQueries({ queryKey: ['subscriptions'] });
                                        toast.success(`已刷新 "${sub.title}"`);
                                    }).catch((err: Error) => {
                                        toast.error(`刷新失败: ${err.message}`);
                                    });
                                }}
                            />
                        </motion.div>
                    ))}
                </AnimatePresence>
            </div>

            <AddSubscriptionModal
                isOpen={isAddModalOpen}
                onClose={() => setIsAddModalOpen(false)}
            />
        </div>
    );
}

function SubscriptionCard({
    subscription,
    onDelete,
    onRefresh,
}: {
    subscription: Subscription;
    onDelete: () => void;
    onRefresh: () => void;
}) {
    const [isRefreshing, setIsRefreshing] = useState(false);
    const progress = subscription.progress;
    const progressPercent = progress.total > 0
        ? Math.round((progress.downloaded / progress.total) * 100)
        : 0;

    const handleRefresh = async () => {
        setIsRefreshing(true);
        try {
            await onRefresh();
        } finally {
            setIsRefreshing(false);
        }
    };

    return (
        <div className="card subscription-card">
            <div className="subscription-header">
                <div className="subscription-info">
                    <h3 className="subscription-title">
                        {subscription.title}
                        {subscription.year && (
                            <span className="subscription-year"> ({subscription.year})</span>
                        )}
                    </h3>
                    <div className="subscription-meta">
                        <span className={`tag ${subscription.type === 'tv' ? 'tag-primary' : 'tag-success'} tag-with-icon`}>
                            {subscription.type === 'tv' ? <Tv size={14} /> : <Clapperboard size={14} />}
                            {subscription.type === 'tv' ? '剧集' : '电影'}
                        </span>
                        {(subscription.season_filter ?? 0) > 0 && (
                            <span className="tag tag-secondary">第 {subscription.season_filter} 季</span>
                        )}
                        <span
                            className={`tag ${subscription.status === 'finished' ? 'tag-success' : 'tag-secondary'} tag-with-icon`}
                        >
                            {subscription.status === 'finished' ? <CheckCircle2 size={14} /> : <Clock size={14} />}
                            {subscription.status_text || (subscription.status === 'finished' ? '已完成' : '更新中')}
                        </span>
                        <span className="text-sm text-secondary" style={{ marginLeft: 8 }}>
                            {new Date(subscription.created_at * 1000).toLocaleDateString()}
                        </span>
                    </div>
                </div>
                <div style={{ display: 'flex', gap: 'var(--spacing-xs)' }}>
                    <button
                        className="btn btn-ghost btn-icon"
                        onClick={handleRefresh}
                        disabled={isRefreshing}
                        title="刷新本地文件状态"
                    >
                        <RefreshCw size={18} className={isRefreshing ? 'animate-spin' : ''} />
                    </button>
                    <button className="btn btn-ghost btn-icon text-error" onClick={onDelete} title="删除订阅">
                        <Trash2 size={18} />
                    </button>
                </div>
            </div>

            {/* 进度 */}
            <div className="subscription-progress">
                <div className="progress">
                    <div
                        className={`progress-bar ${progressPercent >= 100 ? 'success' : ''}`}
                        style={{ width: `${progressPercent}%` }}
                    />
                </div>
                <div className="progress-stats">
                    <span className="stat-item"><HardDrive size={14} /> 下载: {progress.downloaded}/{progress.total}</span>
                    <span className="stat-item"><Check size={14} /> 整理: {progress.organized}/{progress.total}</span>
                </div>
            </div>
        </div>
    );
}

function AddSubscriptionModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
    const [keyword, setKeyword] = useState('');
    const [searchType, setSearchType] = useState<'tv' | 'movie'>('tv');
    type TmdbSearchItem = {
        id: number;
        title: string;
        poster_path?: string | null;
        first_air_date?: string;
        number_of_seasons?: number | null;
    };

    const [selectedItem, setSelectedItem] = useState<TmdbSearchItem | null>(null);
    const [seasonFilter, setSeasonFilter] = useState('');
    const queryClient = useQueryClient();
    const toast = useToast();

    const { data: searchData, isFetching, refetch } = useQuery({
        queryKey: ['tmdb-search', keyword, searchType],
        queryFn: () => api.searchTmdb(keyword, searchType),
        enabled: false, // 手动触发
    });

    // 当选中剧集时，获取详情（主要是季数）
    const selectedId = selectedItem?.id;
    const { data: detailData } = useQuery({
        queryKey: ['tmdb-detail', selectedId],
        queryFn: () => api.getTmdbDetail(String(selectedId), 'tv'),
        enabled: !!selectedId && searchType === 'tv',
    });

    const addMutation = useMutation({
        mutationFn: (data: { tmdbId: string; subType: string; seasonFilter?: number }) =>
            api.addSubscription(data.tmdbId, data.subType, data.seasonFilter),
        onSuccess: () => {
            toast.success('订阅添加成功');
            queryClient.invalidateQueries({ queryKey: ['subscriptions'] });
            onClose();
            setKeyword('');
            setSelectedItem(null);
            setSeasonFilter('');
        },
        onError: (err: Error) => toast.error(`添加失败: ${err.message}`),
    });

    const handleSearch = (e: React.FormEvent) => {
        e.preventDefault();
        if (!keyword.trim()) return;
        setSelectedItem(null);
        setSeasonFilter('');
        refetch().then((result) => {
            // 如果后端返回了季号，自动填充到 seasonFilter
            if (result.data?.season && searchType === 'tv') {
                setSeasonFilter(String(result.data.season));
                toast.info(`已识别季号: 第 ${result.data.season} 季`);
            }
        });
    };

    const handleAdd = () => {
        if (!selectedItem) return;
        const season = seasonFilter ? parseInt(seasonFilter) : undefined;
        addMutation.mutate({
            tmdbId: String(selectedItem.id),
            subType: searchType,
            seasonFilter: season,
        });
    };

    const handleSelectItem = (item: TmdbSearchItem) => {
        setSelectedItem(item);
        // 如果之前没有季号，清空季号选择
        if (!searchData?.season) {
            setSeasonFilter('');
        }
    };

    if (!isOpen) return null;

    return (
        <div className="modal-overlay">
            <motion.div
                className="modal-content"
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
            >
                <div className="modal-header">
                    <h2>添加订阅</h2>
                    <button className="btn btn-ghost btn-icon" onClick={onClose}>
                        <X size={20} />
                    </button>
                </div>

                <div className="modal-body">
                    {/* 搜索栏 */}
                    <form className="search-form" onSubmit={handleSearch}>
                        <div className="input-group">
                            <select
                                className="select search-type-select"
                                value={searchType}
                                onChange={(e) => setSearchType(e.target.value as 'tv' | 'movie')}
                            >
                                <option value="tv">剧集</option>
                                <option value="movie">电影</option>
                            </select>
                            <input
                                type="text"
                                className="input search-input"
                                placeholder="输入名称搜索..."
                                value={keyword}
                                onChange={(e) => setKeyword(e.target.value)}
                                autoFocus
                            />
                            <button type="submit" className="btn btn-primary btn-icon" disabled={isFetching}>
                                {isFetching ? <Loader2 size={18} className="animate-spin" /> : <Search size={18} />}
                            </button>
                        </div>
                    </form>

                    {/* 搜索结果 */}
                    <div className="search-results">
                        {isFetching ? (
                            <div className="loading-state">
                                <Loader2 size={48} className="spinner" />
                                <p>搜索中...</p>
                            </div>
                        ) : searchData?.results && searchData.results.length > 0 ? (
                            <div className="results-grid">
                                {searchData.results.map((item) => (
                                    <div
                                        key={item.id}
                                        className={`result-item ${selectedItem?.id === item.id ? 'selected' : ''}`}
                                        onClick={() => handleSelectItem(item)}
                                    >
                                        <div className="poster-wrapper">
                                            {item.poster_path ? (
                                                <img
                                                    src={`https://image.tmdb.org/t/p/w200${item.poster_path}`}
                                                    alt={item.title}
                                                    loading="lazy"
                                                />
                                            ) : (
                                                <div className="no-poster">
                                                    {searchType === 'tv' ? <Tv size={24} /> : <Clapperboard size={24} />}
                                                </div>
                                            )}
                                        </div>
                                        <div className="result-info">
                                            <h4 className="result-title">{item.title}</h4>
                                            <p className="result-year">
                                                {item.first_air_date ? item.first_air_date.substring(0, 4) : '未知年份'}
                                            </p>
                                        </div>
                                        {selectedItem?.id === item.id && (
                                            <div className="selected-overlay">
                                                <CheckCircle2 size={32} className="text-white" />
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        ) : searchData?.results ? (
                            <div className="empty-state">
                                <AlertCircle size={56} className="empty-icon" />
                                <h3>未找到匹配结果</h3>
                                <p>试试其他关键词或检查拼写</p>
                            </div>
                        ) : (
                            <div className="empty-state">
                                <Search size={56} className="empty-icon" />
                                <h3>开始搜索影视作品</h3>
                                <p>输入剧集或电影名称来查找 TMDB 内容</p>
                            </div>
                        )}
                    </div>

                    {/* 底部操作栏 */}
                    <div className="modal-footer">
                        {selectedItem && searchType === 'tv' && (
                            <div className="season-filter-input">
                                <label>指定季 (可选):</label>
                                {(() => {
                                    const seasons =
                                        (detailData?.number_of_seasons ?? selectedItem.number_of_seasons ?? 0) || 0;
                                    if (seasons > 0) {
                                        const seasonNumbers: number[] = Array.from({ length: seasons }, (_, i) => i + 1);
                                        return (
                                    <select
                                        className="select select-sm"
                                        value={seasonFilter}
                                        onChange={(e) => setSeasonFilter(e.target.value)}
                                    >
                                        <option value="">所有季</option>
                                        {seasonNumbers.map((s) => (
                                            <option key={s} value={s}>
                                                第 {s} 季
                                            </option>
                                        ))}
                                    </select>
                                        );
                                    }
                                    return (
                                    <input
                                        type="number"
                                        className="input input-sm"
                                        placeholder="例如: 1"
                                        value={seasonFilter}
                                        onChange={(e) => setSeasonFilter(e.target.value)}
                                        style={{ width: 80 }}
                                    />
                                    );
                                })()}
                            </div>
                        )}
                        <div className="modal-actions">
                            <button className="btn btn-secondary" onClick={onClose}>取消</button>
                            <button
                                className="btn btn-primary btn-icon"
                                onClick={handleAdd}
                                disabled={!selectedItem || addMutation.isPending}
                            >
                                {addMutation.isPending ? <Loader2 size={18} className="animate-spin" /> : <Plus size={18} />}
                                添加订阅
                            </button>
                        </div>
                    </div>
                </div>
            </motion.div>
        </div>
    );
}
