/**
 * 下载管理页面
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import { useState } from 'react';
import {
    Play, Pause, Trash2, ArrowDown, ArrowUp, Clock, HardDrive,
    FolderInput, CheckSquare, Square, X, Search as SearchIcon,
    ChevronLeft, ChevronRight, AlertTriangle, DownloadCloud, Plus,
    UploadCloud, PauseCircle, CheckCircle2, AlertCircle
} from 'lucide-react';

const PAUSED_STATES = new Set(['pauseddl', 'pausedup', 'stoppeddl', 'stoppedup']);
const QUEUED_STATES = new Set(['queueddl', 'queuedup', 'queuedforchecking']);
const CHECKING_STATES = new Set(['checkingdl', 'checkingup', 'checkingresumedata']);
const ERROR_STATES = new Set(['error', 'missingfiles']);
const DOWNLOADING_STATES = new Set(['downloading', 'forceddl', 'metadl', 'forcedmetadl', 'stalleddl', 'allocating']);
const SEEDING_STATES = new Set(['uploading', 'forcedup', 'stalledup']);

function normalizeStateCode(stateCode?: string): string {
    return (stateCode || 'unknown').toLowerCase();
}

function isPausedState(stateCode?: string): boolean {
    return PAUSED_STATES.has(normalizeStateCode(stateCode));
}

function isSupportedManualDownloadUrl(url: string): boolean {
    const value = (url || '').trim().toLowerCase();
    return value.startsWith('magnet:?') || value.startsWith('http://') || value.startsWith('https://');
}

// 获取下载状态配置（基于 state_code，避免中文文案误判）
function getDownloadStateConfig(stateCode?: string, stateText?: string): { icon: React.ReactNode; text: string; className: string } {
    const code = normalizeStateCode(stateCode);
    const fallbackText = stateText || '未知';

    if (ERROR_STATES.has(code)) {
        return { icon: <AlertCircle size={14} />, text: '错误', className: 'tag-error' };
    }
    if (PAUSED_STATES.has(code)) {
        return { icon: <PauseCircle size={14} />, text: '已暂停', className: 'tag-warning' };
    }
    if (CHECKING_STATES.has(code)) {
        return { icon: <AlertTriangle size={14} />, text: '校验中', className: 'tag-warning' };
    }
    if (QUEUED_STATES.has(code)) {
        return { icon: <Clock size={14} />, text: '排队中', className: 'tag-secondary' };
    }
    if (SEEDING_STATES.has(code)) {
        return { icon: <UploadCloud size={14} />, text: '做种中', className: 'tag-success' };
    }
    if (DOWNLOADING_STATES.has(code)) {
        return { icon: <DownloadCloud size={14} />, text: '下载中', className: 'tag-primary' };
    }

    if (code === 'completed') {
        return { icon: <CheckCircle2 size={14} />, text: '已完成', className: 'tag-success' };
    }

    return { icon: <CheckCircle2 size={14} />, text: fallbackText, className: 'tag-secondary' };
}

function DownloadCard({
    download,
    isSelected,
    onToggleSelect,
    onPause,
    onResume,
    onDelete,
    onOrganize,
    isOrganizing,
}: {
    download: Download;
    isSelected: boolean;
    onToggleSelect: () => void;
    onPause: () => void;
    onResume: () => void;
    onDelete: () => void;
    onOrganize: () => void;
    isOrganizing: boolean;
}) {
    const isPaused = isPausedState(download.state_code);
    const isCompleted = (download.progress ?? 0) >= 100;

    const stateConfig = getDownloadStateConfig(download.state_code, download.state_text || download.state);

    return (
        <div className={`card download-card ${isSelected ? 'selected' : ''}`}>
            {/* 选择框 */}
            {isCompleted && (
                <div className="select-checkbox" onClick={onToggleSelect}>
                    {isSelected ? <CheckSquare size={20} className="text-primary" /> : <Square size={20} className="text-secondary" />}
                </div>
            )}

            <div className="download-main">
                <div className="download-header">
                    <h3 className="download-name">{download.name}</h3>
                    <span className={`tag ${stateConfig.className} tag-with-icon`}>
                        {stateConfig.icon} {stateConfig.text}
                    </span>
                </div>

                {/* 进度条 */}
                <div className="download-progress">
                    <div className="progress">
                        <motion.div
                            className={`progress-bar ${isCompleted ? 'success' : ''}`}
                            initial={{ width: 0 }}
                            animate={{ width: `${Math.min(download.progress ?? 0, 100)}%` }}
                            transition={{ duration: 0.3 }}
                        />
                    </div>
                    <span className="progress-text">{(download.progress ?? 0).toFixed(1)}%</span>
                </div>

                {/* 速度信息 */}
                <div className="download-stats">
                    <span className="stat-item"><ArrowDown size={14} /> {formatSpeed(download.dlspeed)}</span>
                    <span className="stat-item"><ArrowUp size={14} /> {formatSpeed(download.upspeed)}</span>
                    {/* 只在下载中且 ETA 合理时显示（< 7天 = 604800秒） */}
                    {!isCompleted && download.eta > 0 && download.eta < 604800 && (
                        <span className="stat-item"><Clock size={14} /> {formatETA(download.eta)}</span>
                    )}
                    <span className="stat-item"><HardDrive size={14} /> {formatSize(download.size)}</span>
                </div>
            </div>

            {/* 操作按钮 */}
            <div className="download-actions">
                <div className="action-group-main">
                    {isCompleted && (
                        <button
                            className="btn btn-success btn-icon btn-sm"
                            onClick={onOrganize}
                            disabled={isOrganizing}
                            title="整理到媒体库"
                        >
                            <FolderInput size={16} /> 整理
                        </button>
                    )}
                    {isPaused ? (
                        <button className="btn btn-secondary btn-icon btn-sm" onClick={onResume} title="继续任务">
                            <Play size={16} /> 继续
                        </button>
                    ) : (
                        <button className="btn btn-secondary btn-icon btn-sm" onClick={onPause} title="暂停任务">
                            <Pause size={16} /> 暂停
                        </button>
                    )}
                </div>
                <button className="btn btn-ghost btn-icon text-error btn-sm" onClick={onDelete} title="删除任务">
                    <Trash2 size={16} />
                </button>
            </div>
        </div>
    );
}
import { api, type Download } from '../api/client';
import { useWebSocket } from '../hooks/useWebSocket';
import { useToast } from '../components/ToastContext';
import './Downloads.css';

type FilterType = 'all' | 'downloading' | 'completed' | 'paused';

export function Downloads() {
    const [filter, setFilter] = useState<FilterType>('all');
    const [page, setPage] = useState(1);
    const [searchQuery, setSearchQuery] = useState('');
    const [searchInput, setSearchInput] = useState('');
    const [selectedHashes, setSelectedHashes] = useState<Set<string>>(new Set());
    const [isManualModalOpen, setIsManualModalOpen] = useState(false);
    const [manualUrl, setManualUrl] = useState('');
    const [manualCategory, setManualCategory] = useState('');
    const pageSize = 20;

    const queryClient = useQueryClient();
    const { downloads: wsDownloads, isConnected } = useWebSocket();
    const toast = useToast();

    const { data: qbitCategories } = useQuery({
        queryKey: ['qbit-categories'],
        queryFn: () => api.getQbitCategories(),
    });

    const { data, isLoading, error } = useQuery({
        queryKey: ['downloads', page, searchQuery, filter],
        queryFn: () => api.getDownloads({
            page,
            pageSize,
            q: searchQuery || undefined,
            statusFilter: filter !== 'all' ? filter : undefined,
        }),
        refetchInterval: isConnected ? false : 5000,
    });

    // 合并 API 数据和 WebSocket 实时数据
    const downloads = data?.downloads.map((d) => {
        const wsData = wsDownloads.find((ws) => ws.hash === d.hash);
        if (wsData) {
            return {
                ...d,
                progress: wsData.progress,
                state_code: wsData.state_code || d.state_code,
                state_text: wsData.state_text || d.state_text,
                state: wsData.state || d.state,
                dlspeed: wsData.dlspeed,
                upspeed: wsData.upspeed,
                eta: wsData.eta,
            };
        }
        return d;
    }) || [];

    // 已完成的下载（可整理）
    const completedDownloads = downloads.filter((d) => (d.progress ?? 0) >= 100);
    const selectedCompletedCount = completedDownloads.filter((d) => selectedHashes.has(d.hash)).length;

    const totalPages = data?.total_pages || 0;
    const total = data?.total || 0;

    const pauseMutation = useMutation({
        mutationFn: (hash: string) => api.pauseDownload(hash),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['downloads'] }),
        onError: (error: Error) => toast.error(`暂停失败: ${error.message}`),
    });

    const resumeMutation = useMutation({
        mutationFn: (hash: string) => api.resumeDownload(hash),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['downloads'] }),
        onError: (error: Error) => toast.error(`恢复失败: ${error.message}`),
    });

    const deleteMutation = useMutation({
        mutationFn: (hash: string) => api.deleteDownload(hash),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['downloads'] }),
        onError: (error: Error) => toast.error(`删除失败: ${error.message}`),
    });

    const organizeMutation = useMutation({
        mutationFn: (hashes: string[]) => api.organizeDownloads(hashes),
        onSuccess: (result) => {
            setSelectedHashes(new Set());
            queryClient.invalidateQueries({ queryKey: ['organize-tasks'] });
            if (result.success) {
                toast.success(result.message);
            } else {
                toast.warning(result.message);
            }
        },
        onError: (error: Error) => {
            toast.error(`整理失败: ${error.message}`);
        },
    });

    const manualAddMutation = useMutation({
        mutationFn: (payload: { url: string; category?: string }) =>
            api.manualAddDownload(payload.url, payload.category),
        onSuccess: () => {
            setIsManualModalOpen(false);
            setManualUrl('');
            setManualCategory('');
            queryClient.invalidateQueries({ queryKey: ['downloads'] });
            toast.success('下载任务已添加');
        },
        onError: (error: Error) => {
            toast.error(`添加失败: ${error.message}`);
        },
    });

    const handleSearch = (e: React.FormEvent) => {
        e.preventDefault();
        setSearchQuery(searchInput);
        setPage(1);
    };

    const toggleSelect = (hash: string) => {
        const newSet = new Set(selectedHashes);
        if (newSet.has(hash)) {
            newSet.delete(hash);
        } else {
            newSet.add(hash);
        }
        setSelectedHashes(newSet);
    };

    const selectAllCompleted = () => {
        const newSet = new Set(selectedHashes);
        completedDownloads.forEach((d) => newSet.add(d.hash));
        setSelectedHashes(newSet);
    };

    const clearSelection = () => {
        setSelectedHashes(new Set());
    };

    const handleBatchOrganize = () => {
        const hashesToOrganize = Array.from(selectedHashes).filter((hash) =>
            completedDownloads.some((d) => d.hash === hash)
        );
        if (hashesToOrganize.length === 0) {
            toast.warning('请选择已完成的任务进行整理');
            return;
        }
        organizeMutation.mutate(hashesToOrganize);
    };

    const handleManualSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        const url = manualUrl.trim();
        if (!url) {
            toast.warning('请填写下载链接');
            return;
        }
        if (!isSupportedManualDownloadUrl(url)) {
            toast.warning('仅支持 magnet 或 http/https 下载链接');
            return;
        }
        manualAddMutation.mutate({
            url,
            category: manualCategory || undefined,
        });
    };

    return (
        <div className="downloads-page">
            <header className="page-header">
                <div className="page-header-main">
                    <h1>下载管理</h1>
                    <p className="page-subtitle">跟踪任务速度、状态与分类</p>
                </div>
                <div className="downloads-header-actions">
                    <button
                        className="btn btn-primary btn-icon"
                        onClick={() => setIsManualModalOpen(true)}
                    >
                        <Plus size={18} /> 下载
                    </button>
                    <div className="connection-status">
                        <span className={`status-dot ${isConnected ? 'online' : 'offline'}`} />
                        <span className="text-sm text-secondary">
                            {isConnected ? '实时更新' : '轮询中'}
                        </span>
                    </div>
                </div>
            </header>

            {/* 搜索框 */}
            <form className="search-bar" onSubmit={handleSearch}>
                <input
                    type="text"
                    className="input search-input"
                    placeholder="搜索下载任务..."
                    value={searchInput}
                    onChange={(e) => setSearchInput(e.target.value)}
                />
                <button type="submit" className="btn btn-primary btn-icon">
                    <SearchIcon size={18} /> 搜索
                </button>
                {searchQuery && (
                    <button
                        type="button"
                        className="btn btn-secondary btn-icon"
                        onClick={() => {
                            setSearchInput('');
                            setSearchQuery('');
                            setPage(1);
                        }}
                    >
                        <X size={18} /> 清除
                    </button>
                )}
            </form>

            {/* 筛选器 + 批量操作 */}
            <div className="filter-bar">
                <div className="filter-tags">
                    {(['all', 'downloading', 'completed', 'paused'] as FilterType[]).map((f) => (
                        <button
                            key={f}
                            className={`tag ${filter === f ? 'tag-primary' : ''}`}
                            onClick={() => {
                                setFilter(f);
                                setPage(1);
                            }}
                        >
                            {f === 'all' && '全部'}
                            {f === 'downloading' && '下载中'}
                            {f === 'completed' && '已完成'}
                            {f === 'paused' && '暂停'}
                        </button>
                    ))}
                </div>

                {/* 批量操作栏 */}
                <div className="batch-actions">
                    {completedDownloads.length > 0 && (
                        <>
                            <button className="btn btn-ghost btn-sm btn-icon" onClick={selectAllCompleted}>
                                <CheckSquare size={16} /> 全选已完成
                            </button>
                            {selectedHashes.size > 0 && (
                                <button className="btn btn-ghost btn-sm btn-icon" onClick={clearSelection}>
                                    <X size={16} /> 清除选择
                                </button>
                            )}
                        </>
                    )}
                    {selectedCompletedCount > 0 && (
                        <button
                            className="btn btn-success btn-icon"
                            onClick={handleBatchOrganize}
                            disabled={organizeMutation.isPending}
                        >
                            {organizeMutation.isPending ? (
                                <><div className="spinner" /> 整理中...</>
                            ) : (
                                <><FolderInput size={18} /> 整理选中 ({selectedCompletedCount})</>
                            )}
                        </button>
                    )}
                </div>

                <span className="text-sm text-secondary">
                    共 {total} 个任务
                </span>
            </div>

            {/* 下载列表 */}
            <div className="downloads-list">
                {isLoading && (
                    <div className="card empty-state">
                        <div className="spinner" />
                        <p>加载中...</p>
                    </div>
                )}

                {error && (
                    <div className="card empty-state">
                        <AlertTriangle size={48} className="empty-state-icon text-error" />
                        <p className="text-error">加载失败: {(error as Error).message}</p>
                    </div>
                )}

                {!isLoading && downloads.length === 0 && (
                    <div className="card empty-state">
                        <HardDrive size={48} className="empty-state-icon" />
                        <p>暂无下载任务</p>
                    </div>
                )}

                <AnimatePresence>
                    {downloads.map((download) => (
                        <motion.div
                            key={download.hash}
                            initial={{ opacity: 0, y: 20 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, x: -20 }}
                            layout
                        >
                            <DownloadCard
                                download={download}
                                isSelected={selectedHashes.has(download.hash)}
                                onToggleSelect={() => toggleSelect(download.hash)}
                                onPause={() => pauseMutation.mutate(download.hash)}
                                onResume={() => resumeMutation.mutate(download.hash)}
                                onDelete={() => {
                                    if (confirm('确定删除此任务？')) {
                                        deleteMutation.mutate(download.hash);
                                    }
                                }}
                                onOrganize={() => organizeMutation.mutate([download.hash])}
                                isOrganizing={organizeMutation.isPending}
                            />
                        </motion.div>
                    ))}
                </AnimatePresence>
            </div>

            {/* 分页 */}
            {totalPages > 1 && (
                <div className="pagination">
                    <button
                        className="btn btn-secondary btn-icon"
                        disabled={page <= 1}
                        onClick={() => setPage((p) => Math.max(1, p - 1))}
                    >
                        <ChevronLeft size={18} /> 上一页
                    </button>
                    <span className="page-info">
                        第 {page} / {totalPages} 页
                    </span>
                    <button
                        className="btn btn-secondary btn-icon"
                        disabled={page >= totalPages}
                        onClick={() => setPage((p) => p + 1)}
                    >
                        下一页 <ChevronRight size={18} />
                    </button>
                </div>
            )}

            {isManualModalOpen && (
                <div
                    className="manual-download-overlay"
                    onClick={() => {
                        if (!manualAddMutation.isPending) {
                            setIsManualModalOpen(false);
                        }
                    }}
                >
                    <motion.div
                        className="manual-download-modal"
                        initial={{ opacity: 0, y: 12, scale: 0.98 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{ opacity: 0, y: 8, scale: 0.98 }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="manual-modal-header">
                            <h2>手动添加下载</h2>
                            <button
                                className="btn btn-ghost btn-icon"
                                onClick={() => setIsManualModalOpen(false)}
                                disabled={manualAddMutation.isPending}
                                title="关闭"
                            >
                                <X size={18} />
                            </button>
                        </div>

                        <form className="manual-download-form" onSubmit={handleManualSubmit}>
                            <div className="manual-field">
                                <label>下载链接</label>
                                <textarea
                                    className="input manual-url-input"
                                    placeholder="粘贴 magnet:?xt=... 或 https://example.com/file.torrent"
                                    value={manualUrl}
                                    onChange={(e) => setManualUrl(e.target.value)}
                                    rows={4}
                                />
                            </div>

                            <div className="manual-field">
                                <label>分类（可选）</label>
                                <select
                                    className="input"
                                    value={manualCategory}
                                    onChange={(e) => setManualCategory(e.target.value)}
                                >
                                    <option value="">默认（不分类）</option>
                                    {Object.entries(qbitCategories?.categories || {})
                                        .sort(([a], [b]) => a.localeCompare(b))
                                        .map(([name, path]) => (
                                            <option key={name} value={name}>
                                                {path ? `${name} (${path})` : name}
                                            </option>
                                        ))}
                                </select>
                                <p className="text-sm text-secondary">
                                    选择分类后，将按 qBittorrent 分类目录规则保存。
                                </p>
                            </div>

                            <div className="manual-modal-actions">
                                <button
                                    type="button"
                                    className="btn btn-secondary"
                                    onClick={() => setIsManualModalOpen(false)}
                                    disabled={manualAddMutation.isPending}
                                >
                                    取消
                                </button>
                                <button
                                    type="submit"
                                    className="btn btn-primary btn-icon"
                                    disabled={manualAddMutation.isPending}
                                >
                                    {manualAddMutation.isPending ? (
                                        <><div className="spinner" /> 添加中...</>
                                    ) : (
                                        <><Plus size={16} /> 创建下载</>
                                    )}
                                </button>
                            </div>
                        </form>
                    </motion.div>
                </div>
            )}
        </div>
    );
}



function formatSpeed(bytesPerSec: number): string {
    if (bytesPerSec < 1024) return `${bytesPerSec} B/s`;
    if (bytesPerSec < 1024 * 1024) return `${(bytesPerSec / 1024).toFixed(1)} KB/s`;
    return `${(bytesPerSec / 1024 / 1024).toFixed(1)} MB/s`;
}

function formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatETA(seconds: number): string {
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
    return `${Math.floor(seconds / 86400)}d`;
}
