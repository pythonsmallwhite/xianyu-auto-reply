import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { MessageSquare, User, Lock, Eye, EyeOff } from 'lucide-react'
import { AuthNavbar, PublicPageFooter } from '@/components/common/AuthNavbar'
import { getDefaultLoginBrandingSettings } from '@/api/settings'
import { login, verifyToken, getRegistrationStatus, getLoginBrandingSettings } from '@/api/auth'
import { useAuthStore } from '@/store/authStore'
import { useUIStore } from '@/store/uiStore'
import { ButtonLoading } from '@/components/common/Loading'
import { POPUP_ANNOUNCEMENT_SHOWN_KEY } from '@/components/common/PopupAnnouncementModal'

export function Login() {
  const navigate = useNavigate()
  const { setAuth, isAuthenticated } = useAuthStore()
  const { addToast } = useUIStore()

  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [registrationEnabled, setRegistrationEnabled] = useState(true)
  const [loginBranding, setLoginBranding] = useState(() => getDefaultLoginBrandingSettings())

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/dashboard')
      return
    }
    const token = localStorage.getItem('auth_token')
    if (token) {
      verifyToken()
        .then((result) => {
          if (result.authenticated) navigate('/dashboard')
        })
        .catch(() => localStorage.removeItem('auth_token'))
    }
  }, [isAuthenticated, navigate])

  useEffect(() => {
    getRegistrationStatus()
      .then((result) => setRegistrationEnabled(result.enabled))
      .catch(() => {})
    getLoginBrandingSettings()
      .then((result) => setLoginBranding(result))
      .catch(() => {})
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username || !password) {
      addToast({ type: 'error', message: '请输入用户名和密码' })
      return
    }
    setLoading(true)
    try {
      const result = await login({ username, password })
      if (result.success && result.token && result.refresh_token) {
        sessionStorage.removeItem(POPUP_ANNOUNCEMENT_SHOWN_KEY)
        setAuth(result.token, result.refresh_token, {
          user_id: result.user_id!,
          username: result.username!,
          is_admin: result.is_admin!,
          account_limit: result.account_limit,
        })
        addToast({ type: 'success', message: '登录成功' })
        navigate('/dashboard')
      } else {
        addToast({ type: 'error', message: result.message || '登录失败' })
      }
    } catch {
      addToast({ type: 'error', message: '登录失败，请检查网络连接' })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 dark:bg-slate-900 transition-colors duration-200">
      <AuthNavbar systemName={loginBranding['login.system_name']} />

      <div className="flex-1 flex pt-14">
        {/* Left side - Branding */}
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.5 }}
          className="hidden lg:flex lg:w-1/2 bg-slate-900 dark:bg-slate-950 relative overflow-hidden"
        >
          <div className="absolute inset-0 bg-gradient-to-br from-blue-600/20 to-transparent" />
          <div className="relative z-10 flex flex-col justify-center px-16">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2, duration: 0.5 }}
              className="flex items-center gap-3 mb-8"
            >
              <div className="w-12 h-12 rounded-xl bg-blue-500 flex items-center justify-center">
                <MessageSquare className="w-6 h-6 text-white" />
              </div>
              <span className="text-2xl font-bold text-white">{loginBranding['login.system_name']}</span>
            </motion.div>
            <motion.h1
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3, duration: 0.5 }}
              className="text-4xl font-bold text-white mb-4 leading-tight whitespace-pre-line"
            >
              {loginBranding['login.system_title']}
            </motion.h1>
            <motion.p
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4, duration: 0.5 }}
              className="text-slate-400 text-lg max-w-md"
            >
              {loginBranding['login.system_description']}
            </motion.p>
          </div>
          <div className="absolute -bottom-32 -left-32 w-96 h-96 rounded-full bg-blue-600/10" />
          <div className="absolute -top-32 -right-32 w-96 h-96 rounded-full bg-blue-600/5" />
        </motion.div>

        {/* Right side - Login form */}
        <div className="flex-1 flex items-center justify-center p-4 sm:p-6">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
            className="w-full max-w-md"
          >
            {/* Mobile header */}
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1, duration: 0.4 }}
              className="lg:hidden text-center mb-8"
            >
              <div className="w-12 h-12 rounded-xl bg-blue-500 text-white mx-auto mb-4 flex items-center justify-center">
                <MessageSquare className="w-6 h-6" />
              </div>
              <h1 className="text-xl font-bold text-slate-900 dark:text-white">{loginBranding['login.system_name']}</h1>
            </motion.div>

            {/* Login Card */}
            <div className="bg-white dark:bg-slate-800 rounded-lg shadow-sm border border-slate-200 dark:border-slate-700 p-5 sm:p-8">
              <div className="mb-6">
                <h2 className="text-xl vben-card-title text-slate-900 dark:text-white">登录</h2>
                <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">欢迎回来，请登录您的账号</p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-3 sm:space-y-4">
                <div className="input-group">
                  <label className="input-label">用户名</label>
                  <div className="relative">
                    <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                    <input
                      type="text"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder="请输入用户名"
                      className="input-ios pl-9"
                    />
                  </div>
                </div>
                <div className="input-group">
                  <label className="input-label">密码</label>
                  <div className="relative">
                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                    <input
                      type={showPassword ? 'text' : 'password'}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="请输入密码"
                      className="input-ios pl-9 pr-9"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                    >
                      {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                <button type="submit" disabled={loading} className="w-full btn-ios-primary">
                  {loading ? <ButtonLoading /> : '登 录'}
                </button>
              </form>

              {registrationEnabled && (
                <div className="mt-6 text-sm text-center">
                  <Link to="/register" className="text-blue-600 dark:text-blue-400 font-medium hover:text-blue-700 dark:hover:text-blue-300">
                    立即注册
                  </Link>
                </div>
              )}
            </div>

            <PublicPageFooter systemName={loginBranding['login.system_name']} />
          </motion.div>
        </div>
      </div>
    </div>
  )
}
