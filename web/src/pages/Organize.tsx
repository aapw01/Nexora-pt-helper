/**
 * 整理记录页面
 */

import { useQuery } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import { useState } from 'react';
import {
    Clapperboard, Tv, HelpCircle, HardDrive,
    CheckCircle2, XCircle, Loader2, Hourglass, Lightbulb,
    ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight
} from 'lucide-react';
import { api } from '../api/client';
import './Organize.css';

interface OrganizeTask {
    task_id?: string;
    torrent_hash?: string;
    torrent_name?: string;
    mode?: string;
    status?: string;
    total_items?: number;
    done_items?: number;
    current_item?: string;
    message?: string;
    file_size_bytes?: number;
    duration_seconds?: number;
    media_type?: string;
    dest_path?: string;
    created_ts?: number;
    started_ts?: number;
    finished_ts?: number;
}

// 格式化时间
function formatTime(ts?: number): string {
    if (!ts) return '';
    const date = new Date(ts * 1000);
    return date.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
}

// 格式化文件大小
function formatSize(bytes?: number): string {
    if (!bytes || bytes <= 0) return '-';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

// 格式化耗时
function formatDuration(seconds?: number): string {
    if (!seconds || seconds <= 0) return '-';
    if (seconds < 60) return `${seconds}秒`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}分${seconds % 60}秒`;
    return `${Math.floor(seconds / 3600)}小时${Math.floor((seconds % 3600) / 60)}分`;
}

// 获取媒体类型显示
function getMediaTypeDisplay(mediaType?: string): { text: string; icon: React.ReactNode } {
    switch (mediaType) {
        case 'movie':
            return { text: '电影', icon: <Clapperboard size={14} /> };
        case 'tv':
            return { text: '剧集', icon: <Tv size={14} /> };
        default:
            return { text: '未知', icon: <HelpCircle size={14} /> };
    }
}

// 获取状态标签
function getStatusTag(status?: string): { text: string; icon: React.ReactNode; className: string } {
    switch (status) {
        case 'success':
            return { text: '已完成', icon: <CheckCircle2 size={12} />, className: 'tag-success' };
        case 'failed':
            return { text: '失败', icon: <XCircle size={12} />, className: 'tag-error' };
        case 'running':
            return { text: '进行中', icon: <Loader2 size={12} className="animate-spin" />, className: 'tag-primary' };
        case 'queued':
            return { text: '排队中', icon: <Hourglass size={12} />, className: 'tag-warning' };
        default:
            return { text: status || '未知', icon: <HelpCircle size={12} />, className: '' };
    }
}

export function Organize() {
    const [page, setPage] = useState(1);
    const [statusFilter, setStatusFilter] = useState<string>('');
    const pageSize = 20;

    const { data: tasksData, isLoading } = useQuery({
        queryKey: ['organize-tasks', page, statusFilter],
        queryFn: () => api.getOrganizeTasks(page, pageSize, statusFilter || undefined),
        refetchInterval: 5000,  // 每5秒刷新（查看进行中的任务）
    });

    const taskList = (tasksData?.tasks || []) as OrganizeTask[];
    const total = tasksData?.total || 0;
    const totalPages = tasksData?.total_pages || 1;
    const runningCount = taskList.filter((t) => t.status === 'running' || t.status === 'queued').length;

    const goToPage = (newPage: number) => {
        if (newPage >= 1 && newPage <= totalPages) {
            setPage(newPage);
        }
    };

    return (
        <div className="organize-page">
            <header className="page-header">
                <div className="page-header-main">
                    <h1>整理记录</h1>
                    <p className="page-subtitle">将完成下载归档、刮削并同步到媒体库</p>
                </div>
                <div className="page-header-right">
                    {runningCount > 0 && (
                        <span className="tag tag-primary">
                            {runningCount} 个任务进行中
                        </span>
                    )}
                    <span className="total-count">共 {total} 条记录</span>
                </div>
            </header>

            {/* 状态过滤 */}
            <div className="filter-bar">
                <div className="filter-buttons">
                    <button
                        className={`filter-btn ${statusFilter === '' ? 'active' : ''}`}
                        onClick={() => { setStatusFilter(''); setPage(1); }}
                    >
                        全部
                    </button>
                    <button
                        className={`filter-btn ${statusFilter === 'success' ? 'active' : ''}`}
                        onClick={() => { setStatusFilter('success'); setPage(1); }}
                    >
                        <CheckCircle2 size={14} /> 成功
                    </button>
                    <button
                        className={`filter-btn ${statusFilter === 'failed' ? 'active' : ''}`}
                        onClick={() => { setStatusFilter('failed'); setPage(1); }}
                    >
                        <XCircle size={14} /> 失败
                    </button>
                    <button
                        className={`filter-btn ${statusFilter === 'running' ? 'active' : ''}`}
                        onClick={() => { setStatusFilter('running'); setPage(1); }}
                    >
                        <Loader2 size={14} /> 进行中
                    </button>
                </div>
                <p className="page-hint">
                    <Lightbulb size={14} />
                    从 <strong>下载管理</strong> 或 <strong>文件管理</strong> 页面触发整理操作
                </p>
            </div>

            {/* 任务列表 */}
            <div className="organize-content">
                {isLoading && (
                    <div className="card empty-state">
                        <div className="spinner" />
                        <p>加载中...</p>
                    </div>
                )}

                {!isLoading && taskList.length === 0 && (
                    <div className="card empty-state">
                        <HardDrive size={48} className="empty-state-icon" />
                        <p>暂无整理记录</p>
                        <p className="text-sm text-secondary">
                            在下载管理页面选择已完成任务进行整理
                        </p>
                    </div>
                )}

                <AnimatePresence>
                    {taskList.map((task, index) => {
                        const statusInfo = getStatusTag(task.status);
                        const mediaTypeInfo = getMediaTypeDisplay(task.media_type);

                        return (
                            <motion.div
                                key={task.task_id || index}
                                className="card task-card"
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0 }}
                                transition={{ delay: index * 0.03 }}
                            >
                                <div className="task-header">
                                    <div className="task-main">
                                        <span className="task-name">
                                            {task.torrent_name || '未知任务'}
                                        </span>
                                        <span className={`tag ${statusInfo.className} tag-with-icon`}>
                                            {statusInfo.icon} {statusInfo.text}
                                        </span>
                                    </div>
                                </div>

                                <div className="task-info-grid">
                                    <div className="task-info-item">
                                        <span className="label">类型</span>
                                        <span className="value value-with-icon">
                                            {mediaTypeInfo.icon} {mediaTypeInfo.text}
                                        </span>
                                    </div>
                                    <div className="task-info-item">
                                        <span className="label">大小</span>
                                        <span className="value">{formatSize(task.file_size_bytes)}</span>
                                    </div>
                                    <div className="task-info-item">
                                        <span className="label">耗时</span>
                                        <span className="value">{formatDuration(task.duration_seconds)}</span>
                                    </div>
                                    <div className="task-info-item">
                                        <span className="label">时间</span>
                                        <span className="value">{formatTime(task.created_ts)}</span>
                                    </div>
                                </div>

                                {/* 进行中显示当前处理项 */}
                                {task.current_item && task.status === 'running' && (
                                    <p className="task-current">
                                        正在处理: {task.current_item}
                                    </p>
                                )}

                                {/* 结果消息 */}
                                {task.message && task.status !== 'running' && (
                                    <p className={`task-message ${task.status === 'failed' ? 'text-error' : ''}`}>
                                        {task.message}
                                    </p>
                                )}
                            </motion.div>
                        );
                    })}
                </AnimatePresence>

                {/* 分页控件 */}
                {totalPages > 1 && (
                    <div className="pagination">
                        <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => goToPage(1)}
                            disabled={page === 1}
                            title="首页"
                        >
                            <ChevronsLeft size={16} />
                        </button>
                        <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => goToPage(page - 1)}
                            disabled={page === 1}
                            title="上一页"
                        >
                            <ChevronLeft size={16} />
                        </button>

                        <span className="pagination-info">
                            第 {page} / {totalPages} 页
                        </span>

                        <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => goToPage(page + 1)}
                            disabled={page === totalPages}
                            title="下一页"
                        >
                            <ChevronRight size={16} />
                        </button>
                        <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => goToPage(totalPages)}
                            disabled={page === totalPages}
                            title="末页"
                        >
                            <ChevronsRight size={16} />
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}
