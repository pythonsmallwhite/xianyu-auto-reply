/**
 * 关于页面
 *
 * 功能：
 * 1. 显示系统信息与当前版本（仅读取本机版本号，不连接上游更新服务器）
 * 2. 显示主要功能介绍
 * 3. 显示原项目作者、贡献者和源码链接（AGPL-3.0 开源协议要求保留来源）
 */
import { useEffect } from 'react'
import {
  BarChart3, Bell, Bot, Code, Github, MessageSquare, Truck, UserCheck,
} from 'lucide-react'
import { useVersionStore } from '@/store/versionStore'

export function About() {
  // 版本号统一由 versionStore 提供，与侧边栏共享同一取值
  const { currentVersion, fetchCurrentVersion } = useVersionStore()

  useEffect(() => {
    fetchCurrentVersion()
  }, [fetchCurrentVersion])

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      {/* Header */}
      <div className="text-center mb-6">
        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500 to-blue-600 mx-auto mb-4 flex items-center justify-center shadow-md">
          <MessageSquare className="w-8 h-8 text-white" />
        </div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">
          闲鱼自动回复管理系统
        </h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
          智能管理您的闲鱼店铺，提升客服效率
        </p>
        {/* 版本 */}
        {currentVersion && (
          <div className="flex items-center justify-center mt-3">
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-gradient-to-r from-emerald-500/10 to-teal-500/10 text-emerald-600 dark:from-emerald-500/20 dark:to-teal-500/20 dark:text-emerald-400 border border-emerald-200/50 dark:border-emerald-500/30">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              <span>v{currentVersion}</span>
            </div>
          </div>
        )}
      </div>

      {/* Features */}
      <div className="vben-card">
        <div className="vben-card-header">
          <h2 className="vben-card-title">主要功能</h2>
        </div>
        <div className="vben-card-body">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {[
              { title: '多账号管理', desc: '同时管理多个账号', icon: UserCheck, color: 'text-blue-500' },
              { title: '智能回复', desc: '关键词自动回复', icon: MessageSquare, color: 'text-green-500' },
              { title: 'AI 助手', desc: '智能处理复杂问题', icon: Bot, color: 'text-purple-500' },
              { title: '订单管理', desc: '无物流发货与取消订单', icon: Truck, color: 'text-orange-500' },
              { title: '消息通知', desc: '多渠道推送', icon: Bell, color: 'text-pink-500' },
              { title: '数据统计', desc: '订单商品分析', icon: BarChart3, color: 'text-cyan-500' },
            ].map((feature, index) => (
              <div
                key={index}
                className="p-4 rounded-lg bg-slate-50 dark:bg-slate-800 flex items-center gap-3"
              >
                <div className={`w-10 h-10 rounded-lg bg-white dark:bg-slate-700 flex items-center justify-center shadow-sm ${feature.color}`}>
                  <feature.icon className="w-5 h-5" />
                </div>
                <div className="text-left">
                  <p className="font-medium text-sm text-slate-900 dark:text-slate-100">{feature.title}</p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">{feature.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Contributors */}
      <div className="vben-card">
        <div className="vben-card-header">
          <h2 className="vben-card-title">
            <Code className="w-4 h-4" />
            贡献者
          </h2>
        </div>
        <div className="vben-card-body">
          <div className="flex flex-wrap gap-3">
            <a
              href="https://github.com/zhinianboke"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
            >
              <Github className="w-4 h-4 text-slate-600 dark:text-slate-300" />
              <span className="text-sm font-medium text-slate-700 dark:text-slate-200">zhinianboke</span>
              <span className="text-xs text-slate-500 dark:text-slate-400">项目作者</span>
            </a>
            <a
              href="https://github.com/legeling"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
            >
              <Github className="w-4 h-4 text-slate-600 dark:text-slate-300" />
              <span className="text-sm font-medium text-slate-700 dark:text-slate-200">legeling</span>
              <span className="text-xs text-slate-500 dark:text-slate-400">前端重构</span>
            </a>
          </div>
        </div>
      </div>

      {/* Links */}
      <div className="vben-card">
        <div className="vben-card-header">
          <h2 className="vben-card-title">相关链接</h2>
        </div>
        <div className="vben-card-body">
          <div className="flex gap-3">
            <a
              href="https://github.com/zhinianboke/xianyu-auto-reply"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gray-900 text-white hover:bg-gray-800 transition-colors text-sm"
            >
              <Github className="w-4 h-4" />
              <span>原项目源码</span>
            </a>
          </div>
        </div>
      </div>
    </div>
  )
}
