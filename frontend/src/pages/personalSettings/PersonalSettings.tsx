/**
 * 个人设置页面
 * 
 * 功能：
 * 1. 账户信息展示
 * 2. 外部接口秘钥查看、复制与更换
 * 3. 修改登录密码
 * 4. 位置聊天远程接口配置
 */
import { useState, useEffect } from 'react'
import { User, RefreshCw, Key, Link2, Copy, RotateCcw, Save } from 'lucide-react'
import { getUserSetting, updateUserSetting, changePassword, getSecretKey, resetSecretKey, testLocationChatRemoteApi } from '@/api/settings'
import { useUIStore } from '@/store/uiStore'
import { useAuthStore } from '@/store/authStore'
import { PageLoading, ButtonLoading } from '@/components/common/Loading'
import { ConfirmModal } from '@/components/common/ConfirmModal'

const LOCATION_CHAT_REMOTE_URL_KEY = 'location_chat.remote_url'
const LOCATION_CHAT_REMOTE_SECRET_KEY = 'location_chat.remote_secret_key'

export function PersonalSettings() {
  const { addToast } = useUIStore()
  const { isAuthenticated, token, _hasHydrated, user, clearAuth } = useAuthStore()
  const [loading, setLoading] = useState(true)

  // 外部接口秘钥状态
  const [secretKey, setSecretKey] = useState('')
  const [secretKeyLoading, setSecretKeyLoading] = useState(false)
  const [resettingSecretKey, setResettingSecretKey] = useState(false)
  const [secretKeyResetConfirmOpen, setSecretKeyResetConfirmOpen] = useState(false)

  // 密码修改状态
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [changingPassword, setChangingPassword] = useState(false)
  const [activeTab, setActiveTab] = useState<'basic' | 'remote'>('basic')
  const [locationRemoteUrl, setLocationRemoteUrl] = useState('')
  const [locationRemoteSecretKey, setLocationRemoteSecretKey] = useState('')
  const [testingLocationRemote, setTestingLocationRemote] = useState(false)
  const [savingLocationRemote, setSavingLocationRemote] = useState(false)

  // 加载个人设置
  const loadSettings = async () => {
    if (!_hasHydrated || !isAuthenticated || !token) return
    try {
      setLoading(true)
      const locationUrlResult = await getUserSetting(LOCATION_CHAT_REMOTE_URL_KEY)
      setLocationRemoteUrl(locationUrlResult.value || '')
      const locationSecretResult = await getUserSetting(LOCATION_CHAT_REMOTE_SECRET_KEY)
      setLocationRemoteSecretKey(locationSecretResult.value || '')
    } catch {
      // 加载失败时保持空配置
    } finally {
      setLoading(false)
    }
  }

  // 加载外部接口秘钥
  const loadSecretKey = async () => {
    try {
      setSecretKeyLoading(true)
      const result = await getSecretKey()
      if (result.success && result.secret_key) {
        setSecretKey(result.secret_key)
      }
    } catch {
      // 静默失败
    } finally {
      setSecretKeyLoading(false)
    }
  }

  // 更换外部接口秘钥
  const handleResetSecretKey = async () => {
    try {
      setResettingSecretKey(true)
      const result = await resetSecretKey()
      if (result.success) {
        addToast({ type: 'success', message: '外部接口秘钥已更换' })
        if (result.data?.secret_key) {
          setSecretKey(result.data.secret_key)
        } else {
          await loadSecretKey()
        }
      } else {
        addToast({ type: 'error', message: result.message || '更换失败' })
      }
    } catch {
      addToast({ type: 'error', message: '更换外部接口秘钥失败' })
    } finally {
      setResettingSecretKey(false)
      setSecretKeyResetConfirmOpen(false)
    }
  }

  // 复制外部接口秘钥
  const handleCopySecretKey = () => {
    if (!secretKey) return
    navigator.clipboard.writeText(secretKey).then(() => {
      addToast({ type: 'success', message: '外部接口秘钥已复制到剪贴板' })
    }).catch(() => {
      addToast({ type: 'error', message: '复制失败，请手动复制' })
    })
  }

  useEffect(() => {
    loadSettings()
    loadSecretKey()
  }, [_hasHydrated, isAuthenticated, token])

  // 修改密码
  const handleChangePassword = async () => {
    if (!currentPassword) {
      addToast({ type: 'warning', message: '请输入当前密码' })
      return
    }
    if (!newPassword) {
      addToast({ type: 'warning', message: '请输入新密码' })
      return
    }
    if (newPassword !== confirmPassword) {
      addToast({ type: 'warning', message: '两次输入的密码不一致' })
      return
    }
    if (newPassword.length < 6) {
      addToast({ type: 'warning', message: '新密码长度不能少于6位' })
      return
    }
    try {
      setChangingPassword(true)
      const result = await changePassword({ current_password: currentPassword, new_password: newPassword })
      if (result.success) {
        addToast({ type: 'success', message: '密码修改成功，即将退出登录' })
        setCurrentPassword('')
        setNewPassword('')
        setConfirmPassword('')
        // 延迟1秒后退出登录
        setTimeout(() => {
          clearAuth()
          window.location.href = '/login'
        }, 1000)
      } else {
        addToast({ type: 'error', message: result.message || '密码修改失败' })
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string; message?: string } }; message?: string }
      const errorMsg = err?.response?.data?.detail || err?.response?.data?.message || err?.message || '密码修改失败'
      addToast({ type: 'error', message: errorMsg })
    } finally {
      setChangingPassword(false)
    }
  }

  const handleTestLocationRemote = async () => {
    const url = locationRemoteUrl.trim()
    const secretKey = locationRemoteSecretKey.trim()
    if (!url || !secretKey) {
      addToast({ type: 'warning', message: '请输入远程URL和秘钥' })
      return
    }
    try {
      setTestingLocationRemote(true)
      const result = await testLocationChatRemoteApi(url, secretKey)
      if (result.success || result.data?.status_code === 200) {
        addToast({ type: 'success', message: '测试成功' })
      } else {
        addToast({ type: 'error', message: result.message || '测试失败' })
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string; message?: string } }; message?: string }
      addToast({ type: 'error', message: err?.response?.data?.detail || err?.response?.data?.message || err?.message || '测试失败' })
    } finally {
      setTestingLocationRemote(false)
    }
  }

  const handleSaveLocationRemote = async () => {
    const url = locationRemoteUrl.trim()
    const secretKey = locationRemoteSecretKey.trim()
    if (!url || !secretKey) {
      addToast({ type: 'warning', message: '请输入远程URL和秘钥' })
      return
    }
    try {
      setSavingLocationRemote(true)
      const [urlResult, secretResult] = await Promise.all([
        updateUserSetting(LOCATION_CHAT_REMOTE_URL_KEY, url, '位置聊天远程URL'),
        updateUserSetting(LOCATION_CHAT_REMOTE_SECRET_KEY, secretKey, '位置聊天远程秘钥'),
      ])
      if (!urlResult.success || !secretResult.success) {
        addToast({ type: 'error', message: urlResult.message || secretResult.message || '保存失败' })
        return
      }
      setLocationRemoteUrl(url)
      setLocationRemoteSecretKey(secretKey)
      addToast({ type: 'success', message: '位置聊天远程配置已保存' })
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string; message?: string } }; message?: string }
      addToast({ type: 'error', message: err?.response?.data?.detail || err?.response?.data?.message || err?.message || '保存失败' })
    } finally {
      setSavingLocationRemote(false)
    }
  }

  if (loading) {
    return <PageLoading />
  }

  return (
    <div className="space-y-4">
      {/* 页头 */}
      <div className="page-header flex-between flex-wrap gap-4">
        <div>
          <h1 className="page-title">个人设置</h1>
          <p className="page-description">管理个人账户信息和偏好设置</p>
        </div>
        <button onClick={loadSettings} className="btn-ios-secondary">
          <RefreshCw className="w-4 h-4" />
          刷新
        </button>
      </div>

      {/* 账户信息 */}
      <div className="flex gap-1 border-b border-slate-200 dark:border-slate-700">
        <button type="button" onClick={() => setActiveTab('basic')} className={`border-b-2 px-4 py-2 text-sm font-medium transition ${activeTab === 'basic' ? 'border-blue-500 text-blue-600 dark:text-blue-400' : 'border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'}`}>
          基础设置
        </button>
        <button type="button" onClick={() => setActiveTab('remote')} className={`border-b-2 px-4 py-2 text-sm font-medium transition ${activeTab === 'remote' ? 'border-blue-500 text-blue-600 dark:text-blue-400' : 'border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'}`}>
          远程URL配置
        </button>
      </div>

      <div className={activeTab === 'basic' ? 'space-y-4' : 'hidden'}>
      <div className="vben-card">
        <div className="vben-card-header">
          <h2 className="vben-card-title">
            <User className="w-4 h-4" />
            账户信息
          </h2>
        </div>
        <div className="vben-card-body space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="input-label">用户名</label>
              <input
                type="text"
                value={user?.username || ''}
                disabled
                className="input-ios bg-gray-50 dark:bg-gray-800 cursor-not-allowed"
              />
            </div>
            <div>
              <label className="input-label">角色</label>
              <input
                type="text"
                value={user?.is_admin ? '管理员' : '普通用户'}
                disabled
                className="input-ios bg-gray-50 dark:bg-gray-800 cursor-not-allowed"
              />
            </div>
          </div>
        </div>
      </div>

      {/* 外部接口秘钥 */}
      <div className="vben-card">
        <div className="vben-card-header">
          <h2 className="vben-card-title">
            <Key className="w-4 h-4" />
            外部接口秘钥
          </h2>
        </div>
        <div className="vben-card-body space-y-4">
          {/* 秘钥设置 */}
          <div>
            <label className="input-label">秘钥</label>
            <p className="text-xs text-gray-500 mb-2">外部接口秘钥为32位随机字符，全局唯一，用于外部接口（账号/订单/发布/Cookie 回传等）的身份校验。请妥善保管，可随时更换。</p>
            <div className="flex items-center gap-3 flex-wrap">
              {secretKeyLoading ? (
                <div className="text-sm text-gray-400">加载中...</div>
              ) : (
                <div className="flex items-center px-4 py-2.5 bg-gray-50 dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 font-mono text-sm tracking-wider font-semibold text-gray-900 dark:text-white break-all select-all">
                  {secretKey || '-'}
                </div>
              )}
              <button
                onClick={handleCopySecretKey}
                disabled={!secretKey}
                className="btn-ios-secondary text-sm"
                title="复制秘钥"
              >
                <Copy className="w-4 h-4" />
                复制
              </button>
              <button
                onClick={() => setSecretKeyResetConfirmOpen(true)}
                disabled={resettingSecretKey}
                className="btn-ios-secondary text-sm text-amber-600 dark:text-amber-400"
                title="更换秘钥"
              >
                <RotateCcw className={`w-4 h-4 ${resettingSecretKey ? 'animate-spin' : ''}`} />
                更换
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* 修改密码 */}
      <div className="vben-card">
        <div className="vben-card-header">
          <h2 className="vben-card-title">
            <Key className="w-4 h-4" />
            修改密码
          </h2>
        </div>
        <div className="vben-card-body space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="input-group">
              <label className="input-label">当前密码</label>
              <input
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                placeholder="请输入当前密码"
                className="input-ios"
              />
            </div>
            <div />
            <div className="input-group">
              <label className="input-label">新密码</label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="请输入新密码（至少6位）"
                className="input-ios"
              />
            </div>
            <div className="input-group">
              <label className="input-label">确认新密码</label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="请再次输入新密码"
                className="input-ios"
              />
            </div>
          </div>
          <button
            onClick={handleChangePassword}
            disabled={changingPassword}
            className="btn-ios-primary"
          >
            {changingPassword ? <ButtonLoading /> : <Key className="w-4 h-4" />}
            修改密码
          </button>
        </div>
      </div>

      </div>

      {activeTab === 'remote' && (
        <div className="vben-card">
          <div className="vben-card-header">
            <h2 className="vben-card-title">
              <Link2 className="w-4 h-4" />
              位置聊天配置
            </h2>
          </div>
          <div className="vben-card-body space-y-5">
            <p className="text-sm text-slate-500 dark:text-slate-400">
              配置位置消息生成接口，用于测试远程服务是否能够正常生成位置聊天报文。
            </p>
            <div className="space-y-4">
              <div className="input-group">
                <label className="input-label">远程URL</label>
                <input type="url" value={locationRemoteUrl} onChange={(e) => setLocationRemoteUrl(e.target.value)} placeholder="请输入远程接口URL" className="input-ios" />
              </div>
              <div className="input-group">
                <label className="input-label">秘钥</label>
                <input type="password" value={locationRemoteSecretKey} onChange={(e) => setLocationRemoteSecretKey(e.target.value)} placeholder="请输入远程接口秘钥" className="input-ios" autoComplete="off" />
              </div>
              <div className="flex flex-wrap gap-3">
                <button type="button" onClick={handleTestLocationRemote} disabled={testingLocationRemote || savingLocationRemote} className="btn-ios-secondary">
                  {testingLocationRemote ? <ButtonLoading /> : <RefreshCw className="w-4 h-4" />}
                  测试
                </button>
                <button type="button" onClick={handleSaveLocationRemote} disabled={savingLocationRemote || testingLocationRemote} className="btn-ios-primary">
                  {savingLocationRemote ? <ButtonLoading /> : <Save className="w-4 h-4" />}
                  保存
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 更换外部接口秘钥确认弹窗 */}
      <ConfirmModal
        isOpen={secretKeyResetConfirmOpen}
        title="更换秘钥"
        message="确定要更换外部接口秘钥吗？更换后将生成新的32位秘钥，旧秘钥立即失效，调用方需同步更新。"
        confirmText="确定更换"
        cancelText="取消"
        type="warning"
        loading={resettingSecretKey}
        onConfirm={handleResetSecretKey}
        onCancel={() => setSecretKeyResetConfirmOpen(false)}
      />
    </div>
  )
}
