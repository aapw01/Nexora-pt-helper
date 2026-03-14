/**
 * WebSocket Hook
 * 实时接收下载进度更新
 */

import { useEffect, useRef, useState } from 'react';

// 动态构建 WebSocket URL
// 开发环境可以设置 VITE_WS_URL=ws://localhost:8000/ws
// 生产环境使用当前页面的 host
const getWsUrl = () => {
    if (import.meta.env.VITE_WS_URL) {
        return import.meta.env.VITE_WS_URL;
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    return `${protocol}//${host}/ws`;
};

const WS_URL = getWsUrl();

export interface WSMessage {
    type: 'download_update' | 'organize_update' | 'subscription_update';
    data: unknown;
}

export interface DownloadUpdate {
    hash: string;
    name: string;
    progress: number;
    state_code: string;
    state_text: string;
    // 兼容字段：后端仍会返回
    state: string;
    dlspeed: number;
    upspeed: number;
    eta: number;
}

export function useWebSocket(onMessage?: (message: WSMessage) => void) {
    const ws = useRef<WebSocket | null>(null);
    const [isConnected, setIsConnected] = useState(false);
    const [downloads, setDownloads] = useState<DownloadUpdate[]>([]);
    const reconnectTimeout = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
    const onMessageRef = useRef(onMessage);

    // Keep ref updated
    useEffect(() => {
        onMessageRef.current = onMessage;
    }, [onMessage]);

    useEffect(() => {
        const connect = () => {
            if (ws.current?.readyState === WebSocket.OPEN) return;

            ws.current = new WebSocket(WS_URL);

            ws.current.onopen = () => {
                console.log('WebSocket connected');
                setIsConnected(true);
            };

            ws.current.onmessage = (event) => {
                try {
                    const message: WSMessage = JSON.parse(event.data);

                    if (message.type === 'download_update') {
                        setDownloads(message.data as DownloadUpdate[]);
                    }

                    onMessageRef.current?.(message);
                } catch (e) {
                    console.error('Failed to parse WebSocket message:', e);
                }
            };

            ws.current.onclose = () => {
                console.log('WebSocket disconnected');
                setIsConnected(false);

                // 自动重连
                reconnectTimeout.current = setTimeout(() => {
                    connect();
                }, 3000);
            };

            ws.current.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
        };

        connect();

        return () => {
            if (reconnectTimeout.current) {
                clearTimeout(reconnectTimeout.current);
            }
            if (ws.current) {
                ws.current.close();
            }
        };
    }, []);

    const sendPing = () => {
        if (ws.current?.readyState === WebSocket.OPEN) {
            ws.current.send(JSON.stringify({ type: 'ping' }));
        }
    };

    return {
        isConnected,
        downloads,
        sendPing,
    };
}
