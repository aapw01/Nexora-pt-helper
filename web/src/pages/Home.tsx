/**
 * 首页/仪表盘
 */

import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import { Download, Package, Rss, Zap } from 'lucide-react';
import { api } from '../api/client';
import { useWebSocket } from '../hooks/useWebSocket';
import './Home.css';

export function Home() {
    const { data: status, isLoading: statusLoading } = useQuery({
        queryKey: ['status'],
        queryFn: () => api.getStatus(),
        refetchInterval: 30000,
    });

    const { data: downloads } = useQuery({
        queryKey: ['downloads'],
        queryFn: () => api.getDownloads(),
        refetchInterval: 10000,
    });

    const { data: subscriptions } = useQuery({
        queryKey: ['subscriptions'],
        queryFn: () => api.getSubscriptions(),
    });

    const { isConnected } = useWebSocket();

    const activeDownloadStates = new Set(['downloading', 'forceddl', 'metadl', 'forcedmetadl', 'stalleddl', 'allocating']);
    const activeDownloads = downloads?.downloads.filter(
        (d) => activeDownloadStates.has((d.state_code || '').toLowerCase())
    ).length || 0;

    const totalSpeed = downloads?.downloads.reduce((acc, d) => acc + d.dlspeed, 0) || 0;

    return (
        <div className="home">
            <header className="page-header">
                <h1>首页</h1>
                <div className="connection-status">
                    <span className={`status-dot ${isConnected ? 'online' : 'offline'}`} />
                    <span className="text-sm text-secondary">
                        {isConnected ? '实时连接' : '重连中...'}
                    </span>
                </div>
            </header>

            {/* 连接状态 */}
            <section className="status-section">
                <h2 className="section-title">服务状态</h2>
                <div className="grid grid-3">
                    <StatusCard
                        title="M-Team"
                        connected={status?.mteam.connected}
                        message={status?.mteam.message}
                        loading={statusLoading}
                    />
                    <StatusCard
                        title="qBittorrent"
                        connected={status?.qbittorrent.connected}
                        message={status?.qbittorrent.version || '未连接'}
                        loading={statusLoading}
                    />
                    <StatusCard
                        title="TMDB"
                        connected={status?.tmdb.connected}
                        message={status?.tmdb.connected ? '已连接' : '未配置'}
                        loading={statusLoading}
                    />
                </div>
            </section>

            {/* 下载概览 */}
            <section className="stats-section">
                <h2 className="section-title">下载概览</h2>
                <div className="grid grid-4">
                    <StatCard
                        label="活跃下载"
                        value={activeDownloads}
                        icon={<Download size={20} />}
                    />
                    <StatCard
                        label="下载速度"
                        value={formatSpeed(totalSpeed)}
                        icon={<Zap size={20} />}
                    />
                    <StatCard
                        label="所有任务"
                        value={downloads?.total || 0}
                        icon={<Package size={20} />}
                        title="qBittorrent 中的所有任务"
                    />
                    <StatCard
                        label="活跃订阅"
                        value={subscriptions?.subscriptions.filter((s) => s.status !== 'finished').length || 0}
                        icon={<Rss size={20} />}
                    />
                </div>
            </section>

            {/* 快捷操作 */}
            {/* <section className="quick-actions">
                <h2 className="section-title">快捷操作</h2>
                <div className="flex gap-md">
                    <Link to="/search" className="btn btn-primary">
                        搜索资源
                    </Link>
                    <Link to="/subscriptions" className="btn btn-secondary">
                        添加订阅
                    </Link>
                    <Link to="/downloads" className="btn btn-secondary">
                        查看下载
                    </Link>
                </div>
            </section> */}
        </div>
    );
}

function StatusCard({
    title,
    connected,
    message,
    loading,
}: {
    title: string;
    connected?: boolean;
    message?: string;
    loading?: boolean;
}) {
    return (
        <motion.div
            className="card status-card"
            whileHover={{ y: -2 }}
            transition={{ duration: 0.15 }}
        >
            <div className="flex items-center justify-between">
                <span className="font-medium">{title}</span>
                {loading ? (
                    <div className="spinner" />
                ) : (
                    <span className={`status-dot ${connected ? 'online' : 'offline'}`} />
                )}
            </div>
            <p className="text-sm text-secondary">{message || '检查中...'}</p>
        </motion.div>
    );
}

function StatCard({
    label,
    value,
    icon,
    title,
}: {
    label: string;
    value: number | string;
    icon: ReactNode;
    title?: string;
}) {
    return (
        <motion.div
            className="card stat-card"
            whileHover={{ y: -2 }}
            transition={{ duration: 0.15 }}
            title={title}
        >
            <span className="stat-icon">{icon}</span>
            <div className="stat-content">
                <span className="stat-value">{value}</span>
                <span className="stat-label">{label}</span>
            </div>
        </motion.div>
    );
}

function formatSpeed(bytesPerSec: number): string {
    if (bytesPerSec < 1024) return `${bytesPerSec} B/s`;
    if (bytesPerSec < 1024 * 1024) return `${(bytesPerSec / 1024).toFixed(1)} KB/s`;
    return `${(bytesPerSec / 1024 / 1024).toFixed(1)} MB/s`;
}
