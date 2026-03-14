/**
 * Toast 通知组件
 */

import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle2, AlertCircle, AlertTriangle, Info, X } from 'lucide-react';
import { ToastContext, type ToastType } from './ToastContext';
import './Toast.css';

interface Toast {
    id: string;
    message: string;
    type: ToastType;
    duration?: number;
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
    const [toasts, setToasts] = useState<Toast[]>([]);

    const removeToast = useCallback((id: string) => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
    }, []);

    const showToast = useCallback((message: string, type: ToastType = 'info', duration = 3000) => {
        const id = Math.random().toString(36).substring(2, 9);
        setToasts((prev) => [...prev, { id, message, type, duration }]);

        if (duration > 0) {
            setTimeout(() => removeToast(id), duration);
        }
    }, [removeToast]);

    const success = useCallback((message: string) => showToast(message, 'success'), [showToast]);
    const error = useCallback((message: string) => showToast(message, 'error', 5000), [showToast]);
    const warning = useCallback((message: string) => showToast(message, 'warning', 4000), [showToast]);
    const info = useCallback((message: string) => showToast(message, 'info'), [showToast]);

    return (
        <ToastContext.Provider value={{ showToast, success, error, warning, info }}>
            {children}
            <ToastContainer toasts={toasts} onRemove={removeToast} />
        </ToastContext.Provider>
    );
}

function ToastContainer({ toasts, onRemove }: { toasts: Toast[]; onRemove: (id: string) => void }) {
    return (
        <div className="toast-container">
            <AnimatePresence>
                {toasts.map((toast) => (
                    <ToastItem key={toast.id} toast={toast} onRemove={() => onRemove(toast.id)} />
                ))}
            </AnimatePresence>
        </div>
    );
}

function ToastItem({ toast, onRemove }: { toast: Toast; onRemove: () => void }) {
    const [progress, setProgress] = useState(100);

    useEffect(() => {
        if (toast.duration && toast.duration > 0) {
            const interval = 50;
            const step = (100 * interval) / toast.duration;
            const timer = setInterval(() => {
                setProgress((prev) => Math.max(0, prev - step));
            }, interval);
            return () => clearInterval(timer);
        }
    }, [toast.duration]);

    const getIcon = () => {
        switch (toast.type) {
            case 'success': return <CheckCircle2 size={18} />;
            case 'error': return <AlertCircle size={18} />;
            case 'warning': return <AlertTriangle size={18} />;
            case 'info': return <Info size={18} />;
            default: return <Info size={18} />;
        }
    };

    return (
        <motion.div
            className={`toast toast-${toast.type}`}
            initial={{ opacity: 0, y: -30, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -20, scale: 0.95 }}
            transition={{ type: 'spring', stiffness: 400, damping: 25 }}
        >
            <span className="toast-icon">{getIcon()}</span>
            <span className="toast-message">{toast.message}</span>
            <button className="toast-close" onClick={onRemove}><X size={14} /></button>
            {toast.duration && toast.duration > 0 && (
                <div className="toast-progress">
                    <div
                        className="toast-progress-bar"
                        style={{ width: `${progress}%` }}
                    />
                </div>
            )}
        </motion.div>
    );
}
