/**
 * 文件管理页面
 * 浏览文件系统，选择文件/文件夹进行整理
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import { useState, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
    Folder, File, Film, RefreshCw, ChevronRight, Home,
    FolderInput, Eye, AlertTriangle, CheckCircle2, XCircle,
    HardDrive, X, MapPin, FileText, Image,
    FolderOpen, ChevronDown, ChevronUp, Square, CheckSquare, XSquare
} from 'lucide-react';
import { api, type FileItem, type OrganizePreviewResult, type OrganizePreviewFile } from '../api/client';
import { useToast } from '../components/ToastContext';
import './Files.css';

type MediaType = 'auto' | 'movie' | 'tv';
type ModeType = 'copy' | 'move';
type ConflictType = 'skip' | 'rename' | 'overwrite';

function formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatDate(timestamp: number): string {
    if (!timestamp) return '';
    return new Date(timestamp * 1000).toLocaleDateString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
}

function FileIcon({ item }: { item: FileItem }) {
    if (item.is_dir) {
        return (
            <div className="file-icon folder">
                <Folder size={18} />
            </div>
        );
    }
    if (item.is_video) {
        return (
            <div className="file-icon video">
                <Film size={18} />
            </div>
        );
    }
    return (
        <div className="file-icon">
            <File size={18} />
        </div>
    );
}

function Breadcrumb({
    path,
    onNavigate,
    allowedRoots,
}: {
    path: string;
    onNavigate: (path: string) => void;
    allowedRoots: string[];
}) {
    // 找到当前路径所属的根目录
    const currentRoot = useMemo(() => {
        if (!path) return null;
        return allowedRoots.find(root => path === root || path.startsWith(root + '/'));
    }, [path, allowedRoots]);

    // 构建面包屑：只显示从根目录开始的部分
    const parts = useMemo(() => {
        if (!path || !currentRoot) return [];

        // 获取根目录名称
        const rootName = currentRoot.split('/').filter(Boolean).pop() || currentRoot;
        const result: { name: string; path: string; isRoot: boolean }[] = [
            { name: rootName, path: currentRoot, isRoot: true }
        ];

        // 如果当前路径比根目录更深，添加子路径
        if (path !== currentRoot && path.startsWith(currentRoot + '/')) {
            const relativePath = path.slice(currentRoot.length + 1);
            const segments = relativePath.split('/').filter(Boolean);
            let currentPath = currentRoot;
            for (const segment of segments) {
                currentPath += '/' + segment;
                result.push({ name: segment, path: currentPath, isRoot: false });
            }
        }

        return result;
    }, [path, currentRoot]);

    return (
        <div className="breadcrumb">
            <span
                className="breadcrumb-item breadcrumb-link"
                onClick={() => onNavigate('')}
            >
                <Home size={14} /> 根目录
            </span>
            {parts.map((part, index) => (
                <span key={part.path} className="breadcrumb-item">
                    <ChevronRight size={14} className="breadcrumb-separator" />
                    {index === parts.length - 1 ? (
                        <span className="breadcrumb-current">{part.name}</span>
                    ) : (
                        <span
                            className="breadcrumb-link"
                            onClick={() => onNavigate(part.path)}
                        >
                            {part.name}
                        </span>
                    )}
                </span>
            ))}
        </div>
    );
}

// 按目标文件夹分组的预览树
interface GroupedPreview {
    destDir: string;
    files: OrganizePreviewFile[];
    mediaType: string;
}

function groupFilesByDestDir(files: OrganizePreviewFile[]): GroupedPreview[] {
    const groups = new Map<string, OrganizePreviewFile[]>();

    for (const file of files) {
        if (file.status !== 'ok' || !file.dest_dir) continue;
        const dir = file.dest_dir;
        if (!groups.has(dir)) {
            groups.set(dir, []);
        }
        groups.get(dir)!.push(file);
    }

    return Array.from(groups.entries()).map(([destDir, files]) => ({
        destDir,
        files,
        mediaType: files[0]?.media_type || 'unknown',
    }));
}

function PreviewTree({
    result,
    onClose,
    variant = 'inline',
}: {
    result: OrganizePreviewResult;
    onClose: () => void;
    variant?: 'inline' | 'fullscreen';
}) {
    const groupedOk = useMemo(() => groupFilesByDestDir(result.files), [result.files]);
    const skippedFiles = result.files.filter(f => f.status === 'skipped');
    const errorFiles = result.files.filter(f => f.status === 'error');

    // 默认展开第一个目录
    const [expandedDirs, setExpandedDirs] = useState<Set<string>>(() => {
        const grouped = groupFilesByDestDir(result.files);
        return grouped.length > 0 ? new Set([grouped[0].destDir]) : new Set();
    });

    const toggleDir = (dir: string) => {
        const newSet = new Set(expandedDirs);
        if (newSet.has(dir)) {
            newSet.delete(dir);
        } else {
            newSet.add(dir);
        }
        setExpandedDirs(newSet);
    };

    const getFileName = (path: string) => path.split('/').pop() || path;
    const getDirName = (path: string) => {
        const parts = path.split('/');
        return parts.slice(-2).join('/');
    };

    const isFullscreen = variant === 'fullscreen';

    return (
        <motion.div
            className={`preview-tree ${isFullscreen ? 'fullscreen' : ''}`}
            {...(isFullscreen
                ? {
                    // 全屏预览：不能用内联 height 动画覆盖 flex，否则内部滚动区拿不到高度
                    initial: { opacity: 0 },
                    animate: { opacity: 1 },
                    exit: { opacity: 0 },
                    style: { height: '100%' },
                }
                : {
                    initial: { opacity: 0, height: 0 },
                    animate: { opacity: 1, height: 'auto' },
                    exit: { opacity: 0, height: 0 },
                })}
        >
            {/* 头部统计 */}
            <div className="preview-tree-header">
                <div className="preview-tree-title">
                    <FolderOpen size={16} />
                    <span>预览结果</span>
                </div>
                <button className="preview-close" onClick={onClose}>
                    <X size={14} />
                </button>
            </div>

            <div className="preview-tree-stats">
                {result.ok > 0 && (
                    <span className="stat-badge success">
                        <CheckCircle2 size={12} />
                        {result.ok} 可整理
                    </span>
                )}
                {result.skipped > 0 && (
                    <span className="stat-badge warning">
                        <AlertTriangle size={12} />
                        {result.skipped} 跳过
                    </span>
                )}
                {result.bad > 0 && (
                    <span className="stat-badge error">
                        <XCircle size={12} />
                        {result.bad} 失败
                    </span>
                )}
            </div>

            {/* 目标目录卡片列表 */}
            <div className="preview-tree-content">
                {groupedOk.map((group) => (
                    <div key={group.destDir} className="dest-folder-card">
                        {/* 文件夹标题 */}
                        <div
                            className="dest-folder-header"
                            onClick={() => toggleDir(group.destDir)}
                        >
                            <div className="dest-folder-icon">
                                <Folder size={18} />
                            </div>
                            <div className="dest-folder-info">
                                <div className="dest-folder-name">
                                    {getDirName(group.destDir)}
                                </div>
                                <div className="dest-folder-path">
                                    {group.destDir}
                                </div>
                            </div>
                            <div className="dest-folder-count">
                                {group.files.length} 个文件
                            </div>
                            <div className="dest-folder-toggle">
                                {expandedDirs.has(group.destDir) ? (
                                    <ChevronUp size={16} />
                                ) : (
                                    <ChevronDown size={16} />
                                )}
                            </div>
                        </div>

                        {/* 展开的文件树 */}
                        <AnimatePresence>
                            {expandedDirs.has(group.destDir) && (
                                <motion.div
                                    className="dest-folder-files"
                                    initial={{ opacity: 0, height: 0 }}
                                    animate={{ opacity: 1, height: 'auto' }}
                                    exit={{ opacity: 0, height: 0 }}
                                >
                                    {group.files.map((file, idx) => (
                                        <div key={idx} className="file-tree-item">
                                            <div className="file-tree-branch">
                                                {idx === group.files.length - 1 ? '└' : '├'}
                                            </div>
                                            <div className="file-tree-content">
                                                {/* 视频文件 */}
                                                <div className="file-tree-row video">
                                                    <Film size={14} />
                                                    <span className="file-tree-name" title={file.source}>
                                                        {getFileName(file.dest || '')}
                                                    </span>
                                                </div>
                                                {/* 刮削产物 */}
                                                {file.will_scrape && (
                                                    <div className="file-tree-scrape">
                                                        {file.will_scrape.nfo && (
                                                            <div className="file-tree-row scrape">
                                                                <FileText size={12} />
                                                                <span>{getFileName(file.will_scrape.nfo)}</span>
                                                            </div>
                                                        )}
                                                        {file.will_scrape.poster && (
                                                            <div className="file-tree-row scrape">
                                                                <Image size={12} />
                                                                <span>{getFileName(file.will_scrape.poster)}</span>
                                                            </div>
                                                        )}
                                                    </div>
                                                )}
                                                {/* 字幕文件 */}
                                                {file.sidecars && file.sidecars.length > 0 && (
                                                    <div className="file-tree-sidecars">
                                                        {file.sidecars.map((sc, scIdx) => (
                                                            <div key={scIdx} className="file-tree-row sidecar">
                                                                <File size={12} />
                                                                <span>{getFileName(sc)}</span>
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    ))}
                                </motion.div>
                            )}
                        </AnimatePresence>
                    </div>
                ))}

                {/* 识别失败的文件（特殊处理） */}
                {skippedFiles.filter(f => f.reason?.includes('识别失败')).length > 0 && (
                    <div className="unidentified-files-card">
                        <div className="unidentified-header">
                            <XCircle size={14} />
                            <span>识别失败 ({skippedFiles.filter(f => f.reason?.includes('识别失败')).length})</span>
                            <span className="unidentified-hint">这些文件将被跳过</span>
                        </div>
                        <div className="unidentified-list">
                            {skippedFiles.filter(f => f.reason?.includes('识别失败')).slice(0, 5).map((file, idx) => (
                                <div key={idx} className="unidentified-item">
                                    <Film size={14} />
                                    <span className="unidentified-name">{getFileName(file.source)}</span>
                                </div>
                            ))}
                            {skippedFiles.filter(f => f.reason?.includes('识别失败')).length > 5 && (
                                <div className="unidentified-more">
                                    ... 还有 {skippedFiles.filter(f => f.reason?.includes('识别失败')).length - 5} 个
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {/* 其他跳过的文件 */}
                {skippedFiles.filter(f => !f.reason?.includes('识别失败')).length > 0 && (
                    <div className="skipped-files-card">
                        <div className="skipped-header">
                            <AlertTriangle size={14} />
                            <span>已跳过 ({skippedFiles.filter(f => !f.reason?.includes('识别失败')).length})</span>
                        </div>
                        <div className="skipped-list">
                            {skippedFiles.filter(f => !f.reason?.includes('识别失败')).slice(0, 3).map((file, idx) => (
                                <div key={idx} className="skipped-item">
                                    <span className="skipped-name">{getFileName(file.source)}</span>
                                    <span className="skipped-reason">{file.reason}</span>
                                </div>
                            ))}
                            {skippedFiles.filter(f => !f.reason?.includes('识别失败')).length > 3 && (
                                <div className="skipped-more">
                                    ... 还有 {skippedFiles.filter(f => !f.reason?.includes('识别失败')).length - 3} 个
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {/* 失败的文件 */}
                {errorFiles.length > 0 && (
                    <div className="error-files-card">
                        <div className="error-header">
                            <XCircle size={14} />
                            <span>失败 ({errorFiles.length})</span>
                        </div>
                        <div className="error-list">
                            {errorFiles.slice(0, 3).map((file, idx) => (
                                <div key={idx} className="error-item">
                                    <span className="error-name">{getFileName(file.source)}</span>
                                    <span className="error-reason">{file.error}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </motion.div>
    );
}

// 整理弹窗组件
function OrganizeModal({
    items,
    libraries,
    onClose,
    onSuccess,
}: {
    items: FileItem[];  // 支持多个项目
    libraries: { movie?: string; tv?: string };
    onClose: () => void;
    onSuccess: () => void;
}) {
    const [mediaType, setMediaType] = useState<MediaType>('auto');
    const [mode, setMode] = useState<ModeType>('move');
    const [onConflict, setOnConflict] = useState<ConflictType>('skip');
    const [previewResult, setPreviewResult] = useState<OrganizePreviewResult | null>(null);
    const [showPreviewModal, setShowPreviewModal] = useState(false);

    const toast = useToast();
    const queryClient = useQueryClient();

    // 获取所有路径
    const paths = useMemo(() => items.map(i => i.path), [items]);

    // 获取目标目录
    const targetLibrary = useMemo(() => {
        if (mediaType === 'auto') return null;
        return libraries[mediaType] || null;
    }, [mediaType, libraries]);

    // 计算总大小
    const totalSize = useMemo(() => {
        return items.reduce((sum, i) => sum + (i.size || 0), 0);
    }, [items]);

    // 预览整理
    const previewMutation = useMutation({
        mutationFn: () => api.previewOrganize(paths.length === 1 ? paths[0] : paths, mediaType),
        onSuccess: (result) => {
            const preview = result.result;
            // 预览为空：不弹预览框，直接提示
            const totalFiles = preview?.total ?? 0;
            const fileCount = preview?.files?.length ?? 0;
            if (totalFiles <= 0 || fileCount <= 0) {
                toast.warning('未找到可整理的视频文件');
                setPreviewResult(null);
                setShowPreviewModal(false);
                return;
            }
            setPreviewResult(preview);
            setShowPreviewModal(true);
        },
        onError: (error: Error) => {
            toast.error(`预览失败: ${error.message}`);
        },
    });

    // 执行整理
    const organizeMutation = useMutation({
        mutationFn: () => api.organizeFiles({
            paths: paths.length > 1 ? paths : undefined,
            path: paths.length === 1 ? paths[0] : undefined,
            mode,
            media_type: mediaType,
            dry_run: false,
            on_conflict: onConflict,
        }),
        onSuccess: (result) => {
            if (result.success) {
                toast.success(result.message || '整理任务已提交');
                queryClient.invalidateQueries({ queryKey: ['organize-tasks'] });
                onSuccess();
                onClose();
            } else {
                toast.error('整理失败');
            }
        },
        onError: (error: Error) => {
            toast.error(`整理失败: ${error.message}`);
        },
    });

    const handlePreview = () => {
        previewMutation.mutate();
    };

    const handleOrganize = () => {
        organizeMutation.mutate();
    };

    const mediaTypeLabels: Record<MediaType, string> = {
        auto: '自动识别',
        movie: '电影',
        tv: '电视剧',
    };

    return (
        <div className="modal-overlay" onClick={onClose}>
            <motion.div
                className="modal-content organize-modal"
                initial={{ opacity: 0, scale: 0.95, y: 20 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95, y: 20 }}
                transition={{ duration: 0.2 }}
                onClick={(e) => e.stopPropagation()}
            >
                {/* 头部 */}
                <div className="modal-header">
                    <h3 className="modal-title">整理到媒体库</h3>
                    <button className="modal-close" onClick={onClose}>
                        <X size={20} />
                    </button>
                </div>

                {/* 内容 */}
                <div className="modal-body">
                    {/* 选中项信息 */}
                    {items.length === 1 ? (
                        <div className="selected-item-info">
                            <FileIcon item={items[0]} />
                            <div className="selected-item-details">
                                <span className="selected-item-name">{items[0].name}</span>
                                {!items[0].is_dir && (
                                    <span className="selected-item-size">
                                        {formatSize(items[0].size)}
                                    </span>
                                )}
                            </div>
                        </div>
                    ) : (
                        <div className="selected-items-summary">
                            <div className="selected-items-count">
                                <CheckSquare size={18} />
                                <span>已选择 <strong>{items.length}</strong> 个项目</span>
                            </div>
                            <div className="selected-items-breakdown">
                                {items.filter(i => i.is_dir).length > 0 && (
                                    <span className="breakdown-item">
                                        <Folder size={14} />
                                        {items.filter(i => i.is_dir).length} 个文件夹
                                    </span>
                                )}
                                {items.filter(i => i.is_video).length > 0 && (
                                    <span className="breakdown-item">
                                        <Film size={14} />
                                        {items.filter(i => i.is_video).length} 个视频
                                    </span>
                                )}
                                {totalSize > 0 && (
                                    <span className="breakdown-item total-size">
                                        共 {formatSize(totalSize)}
                                    </span>
                                )}
                            </div>
                        </div>
                    )}

                    {/* 媒体类型 */}
                    <div className="form-group">
                        <label className="form-label">媒体类型</label>
                        <div className="type-buttons">
                            {(['auto', 'movie', 'tv'] as MediaType[]).map((type) => (
                                <button
                                    key={type}
                                    className={`type-button ${mediaType === type ? 'selected' : ''}`}
                                    onClick={() => {
                                        setMediaType(type);
                                        setPreviewResult(null);
                                        setShowPreviewModal(false);
                                    }}
                                >
                                    {mediaTypeLabels[type]}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* 目标目录（当选择具体类型时显示） */}
                    {targetLibrary && (
                        <div className="form-group">
                            <label className="form-label">
                                <MapPin size={14} /> 目标目录
                            </label>
                            <div className="target-path">
                                {targetLibrary}
                            </div>
                        </div>
                    )}

                    {/* 整理动作 */}
                    <div className="form-group">
                        <label className="form-label">整理动作</label>
                        <div className="radio-group">
                            <div
                                className={`radio-option ${mode === 'move' ? 'selected' : ''}`}
                                onClick={() => setMode('move')}
                            >
                                移动
                            </div>
                            <div
                                className={`radio-option ${mode === 'copy' ? 'selected' : ''}`}
                                onClick={() => setMode('copy')}
                            >
                                复制
                            </div>
                        </div>
                    </div>

                    {/* 冲突处理 */}
                    <div className="form-group">
                        <label className="form-label">冲突处理</label>
                        <select
                            className="select"
                            value={onConflict}
                            onChange={(e) => setOnConflict(e.target.value as ConflictType)}
                        >
                            <option value="skip">跳过</option>
                            <option value="rename">重命名</option>
                            <option value="overwrite">覆盖</option>
                        </select>
                    </div>

                </div>

                {/* 底部按钮 */}
                <div className="modal-footer">
                    <button
                        className="btn btn-secondary btn-icon"
                        onClick={handlePreview}
                        disabled={previewMutation.isPending}
                    >
                        {previewMutation.isPending ? (
                            <><div className="spinner" /> 预览中...</>
                        ) : (
                            <><Eye size={16} /> 预览</>
                        )}
                    </button>
                    <button
                        className="btn btn-success btn-icon"
                        onClick={handleOrganize}
                        disabled={organizeMutation.isPending}
                    >
                        {organizeMutation.isPending ? (
                            <><div className="spinner" /> 整理中...</>
                        ) : (
                            <><FolderInput size={16} /> 开始整理</>
                        )}
                    </button>
                </div>
            </motion.div>

            {/* 全屏预览弹窗（更清晰的展示） */}
            <AnimatePresence>
                {showPreviewModal && previewResult && (
                    <div className="modal-overlay preview-overlay" onClick={() => setShowPreviewModal(false)}>
                        <motion.div
                            className="modal-content preview-modal"
                            initial={{ opacity: 0, scale: 0.98, y: 20 }}
                            animate={{ opacity: 1, scale: 1, y: 0 }}
                            exit={{ opacity: 0, scale: 0.98, y: 20 }}
                            transition={{ duration: 0.18 }}
                            onClick={(e) => e.stopPropagation()}
                        >
                            <div className="preview-modal-body">
                                <PreviewTree
                                    result={previewResult}
                                    onClose={() => setShowPreviewModal(false)}
                                    variant="fullscreen"
                                />
                            </div>
                            <div className="preview-modal-footer">
                                <button
                                    className="btn btn-secondary btn-icon"
                                    onClick={() => setShowPreviewModal(false)}
                                >
                                    <X size={16} /> 返回
                                </button>
                                <button
                                    className="btn btn-success btn-icon"
                                    onClick={() => {
                                        // 先关闭预览弹窗，再提交整理任务
                                        setShowPreviewModal(false);
                                        handleOrganize();
                                    }}
                                    disabled={organizeMutation.isPending}
                                >
                                    {organizeMutation.isPending ? (
                                        <><div className="spinner" /> 整理中...</>
                                    ) : (
                                        <><FolderInput size={16} /> 开始整理</>
                                    )}
                                </button>
                            </div>
                        </motion.div>
                    </div>
                )}
            </AnimatePresence>
        </div>
    );
}

export function Files() {
    const [searchParams, setSearchParams] = useSearchParams();
    const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
    const [showModal, setShowModal] = useState(false);
    const [lastClickedIndex, setLastClickedIndex] = useState<number | null>(null);

    // 从 URL 参数读取当前路径
    const currentPath = searchParams.get('path') || '';

    // 设置当前路径（同时更新 URL）
    const setCurrentPath = (path: string) => {
        if (path) {
            setSearchParams({ path });
        } else {
            setSearchParams({});
        }
    };

    // 获取允许的根目录列表
    const { data: rootsData } = useQuery({
        queryKey: ['fs-roots'],
        queryFn: () => api.getFsRoots(),
    });

    // 获取媒体库配置
    const { data: librariesData } = useQuery({
        queryKey: ['fs-libraries'],
        queryFn: () => api.getLibraries(),
    });

    const allowedRoots = useMemo(() => {
        return (rootsData?.roots || []).map(r => r.path);
    }, [rootsData]);

    const libraries = librariesData?.libraries || {};

    // 获取目录列表
    const { data: listData, isLoading, error, refetch } = useQuery({
        queryKey: ['fs-list', currentPath],
        queryFn: () => api.listDirectory(currentPath || undefined),
    });

    // eslint 规则建议：避免 `listData?.items || []` 这种在 render 中生成新引用
    const items = useMemo(() => listData?.items || [], [listData]);

    // 获取选中的项目
    const selectedItems = useMemo(() => {
        return items.filter(item => selectedPaths.has(item.path));
    }, [items, selectedPaths]);

    // 可选中的项目（文件夹或视频文件）
    const selectableItems = useMemo(() => {
        return items.filter(item => item.is_dir || item.is_video);
    }, [items]);

    // 是否全选
    const isAllSelected = selectableItems.length > 0 &&
        selectableItems.every(item => selectedPaths.has(item.path));

    // 切换选中状态
    const toggleSelect = (item: FileItem, index: number, shiftKey: boolean) => {
        const newSelected = new Set(selectedPaths);

        if (shiftKey && lastClickedIndex !== null) {
            // Shift+点击：范围选择
            const start = Math.min(lastClickedIndex, index);
            const end = Math.max(lastClickedIndex, index);
            for (let i = start; i <= end; i++) {
                const targetItem = selectableItems[i];
                if (targetItem) {
                    newSelected.add(targetItem.path);
                }
            }
        } else {
            // 普通点击：切换单个
            if (newSelected.has(item.path)) {
                newSelected.delete(item.path);
            } else {
                newSelected.add(item.path);
            }
        }

        setSelectedPaths(newSelected);
        setLastClickedIndex(index);
    };

    // 全选/取消全选
    const toggleSelectAll = () => {
        if (isAllSelected) {
            setSelectedPaths(new Set());
        } else {
            setSelectedPaths(new Set(selectableItems.map(item => item.path)));
        }
    };

    // 清除选择
    const clearSelection = () => {
        setSelectedPaths(new Set());
        setLastClickedIndex(null);
    };

    const handleItemClick = (item: FileItem) => {
        if (item.is_dir) {
            // 目录：进入（如果没有多选状态）
            if (selectedPaths.size === 0) {
                setCurrentPath(item.path);
                clearSelection();
            }
        }
    };

    const handleItemDoubleClick = (item: FileItem) => {
        if (item.is_dir) {
            // 双击目录：始终进入
            setCurrentPath(item.path);
            clearSelection();
        } else if (item.is_video) {
            // 双击视频：打开整理弹窗
            setSelectedPaths(new Set([item.path]));
            setShowModal(true);
        }
    };

    const handleNavigate = (path: string) => {
        setCurrentPath(path);
        clearSelection();
    };

    const handleCloseModal = () => {
        setShowModal(false);
    };

    const handleOrganizeSuccess = () => {
        // 刷新当前目录并清除选择
        refetch();
        clearSelection();
    };

    const openOrganizeModal = () => {
        if (selectedItems.length > 0) {
            setShowModal(true);
        }
    };

    return (
        <div className="files-page">
            <header className="page-header">
                <div className="page-header-main">
                    <h1>文件管理</h1>
                    <p className="page-subtitle">查看文件落点与媒体库结构</p>
                </div>
                <div className="file-toolbar">
                    <button
                        className="btn btn-secondary btn-icon"
                        onClick={() => refetch()}
                        disabled={isLoading}
                    >
                        <RefreshCw size={16} className={isLoading ? 'spinning' : ''} />
                        <span className="btn-text">刷新</span>
                    </button>
                </div>
            </header>

            <Breadcrumb path={currentPath} onNavigate={handleNavigate} allowedRoots={allowedRoots} />

            {/* 选择工具栏 */}
            <AnimatePresence>
                {selectedPaths.size > 0 && (
                    <motion.div
                        className="selection-toolbar"
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -10 }}
                    >
                        <div className="selection-info">
                            <CheckSquare size={16} />
                            <span>已选择 <strong>{selectedPaths.size}</strong> 个项目</span>
                        </div>
                        <div className="selection-actions">
                            <button
                                className="btn btn-ghost btn-sm"
                                onClick={clearSelection}
                            >
                                <XSquare size={16} />
                                <span>取消</span>
                            </button>
                            <button
                                className="btn btn-success btn-sm btn-icon"
                                onClick={openOrganizeModal}
                            >
                                <FolderInput size={16} />
                                <span>整理选中</span>
                            </button>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* 文件列表 */}
            <div className="file-browser card">
                {isLoading && (
                    <div className="file-loading">
                        <div className="spinner" />
                    </div>
                )}

                {error && (
                    <div className="empty-state">
                        <AlertTriangle size={48} className="empty-state-icon text-error" />
                        <p className="text-error">加载失败: {(error as Error).message}</p>
                    </div>
                )}

                {!isLoading && !error && items.length === 0 && (
                    <div className="empty-state">
                        <HardDrive size={48} className="empty-state-icon" />
                        <p>此目录为空</p>
                    </div>
                )}

                {/* 全选按钮 */}
                {selectableItems.length > 0 && (
                    <div className="file-list-header">
                        <button
                            className="btn btn-ghost btn-sm select-all-btn"
                            onClick={toggleSelectAll}
                        >
                            {isAllSelected ? (
                                <><CheckSquare size={16} /> 取消全选</>
                            ) : (
                                <><Square size={16} /> 全选</>
                            )}
                        </button>
                        <span className="file-count">{items.length} 个项目</span>
                    </div>
                )}

                <div className="file-list">
                    {items.map((item) => {
                        const isSelected = selectedPaths.has(item.path);
                        const isSelectable = item.is_dir || item.is_video;
                        const selectableIndex = selectableItems.findIndex(i => i.path === item.path);

                        return (
                            <motion.div
                                key={item.path}
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0 }}
                                className={`file-item ${item.is_dir ? 'is-dir' : ''} ${isSelected ? 'selected' : ''}`}
                                onClick={() => handleItemClick(item)}
                                onDoubleClick={() => handleItemDoubleClick(item)}
                            >
                                {/* 复选框 */}
                                {isSelectable && (
                                    <button
                                        className="file-checkbox"
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            toggleSelect(item, selectableIndex, e.shiftKey);
                                        }}
                                    >
                                        {isSelected ? (
                                            <CheckSquare size={18} className="checked" />
                                        ) : (
                                            <Square size={18} />
                                        )}
                                    </button>
                                )}
                                {!isSelectable && <div className="file-checkbox-placeholder" />}

                                <FileIcon item={item} />
                                <div className="file-info">
                                    <div className="file-name">{item.name}</div>
                                    <div className="file-meta">
                                        {!item.is_dir && <span>{formatSize(item.size)}</span>}
                                        <span className="file-date">{formatDate(item.mtime)}</span>
                                    </div>
                                </div>

                                {/* 单个整理按钮 */}
                                {isSelectable && (
                                    <button
                                        className="btn btn-ghost btn-sm btn-organize"
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            // 选中当前项并打开弹窗
                                            setSelectedPaths(new Set([item.path]));
                                            setShowModal(true);
                                        }}
                                        title={item.is_dir ? '整理此文件夹' : '整理此视频'}
                                    >
                                        <FolderInput size={16} />
                                    </button>
                                )}
                            </motion.div>
                        );
                    })}
                </div>
            </div>

            {/* 整理弹窗 */}
            <AnimatePresence>
                {showModal && selectedItems.length > 0 && (
                    <OrganizeModal
                        items={selectedItems}
                        libraries={libraries}
                        onClose={handleCloseModal}
                        onSuccess={handleOrganizeSuccess}
                    />
                )}
            </AnimatePresence>
        </div>
    );
}
