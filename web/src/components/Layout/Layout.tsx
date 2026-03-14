/**
 * 应用布局组件
 */

import { NavLink, Outlet } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Home, Search, Download, Rss, FolderInput, HardDrive } from 'lucide-react';
import './Layout.css';

const navItems = [
    { path: '/', label: '首页', icon: <Home size={20} /> },
    { path: '/search', label: '搜索', icon: <Search size={20} /> },
    { path: '/downloads', label: '下载', icon: <Download size={20} /> },
    { path: '/subscriptions', label: '订阅', icon: <Rss size={20} /> },
    { path: '/organize', label: '整理', icon: <FolderInput size={20} /> },
    { path: '/files', label: '文件', icon: <HardDrive size={20} /> },
];

export function Layout() {
    return (
        <div className="layout">
            <aside className="sidebar">
                <div className="sidebar-header">
                    <div className="logo-stack">
                        <h1 className="logo">Nexora</h1>
                        <p className="logo-subtitle">让资源从发现到入库自动流转</p>
                    </div>
                </div>
                <nav className="sidebar-nav">
                    {navItems.map((item) => (
                        <NavLink
                            key={item.path}
                            to={item.path}
                            className={({ isActive }) =>
                                `nav-item ${isActive ? 'active' : ''}`
                            }
                        >
                            <span className="nav-icon">{item.icon}</span>
                            <span className="nav-label">{item.label}</span>
                        </NavLink>
                    ))}
                </nav>
            </aside>
            <main className="main-content">
                <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
                >
                    <Outlet />
                </motion.div>
            </main>
        </div>
    );
}
