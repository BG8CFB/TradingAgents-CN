<template>
  <div class="login-page">
    <!-- Left Showcase Panel -->
    <div class="login-showcase">
      <!-- Aurora background layers -->
      <div class="aurora aurora-1"></div>
      <div class="aurora aurora-2"></div>
      <div class="aurora aurora-3"></div>

      <!-- Noise texture overlay -->
      <div class="noise-overlay"></div>

      <!-- Scan line effect -->
      <div class="scan-line"></div>

      <!-- Particle canvas -->
      <canvas ref="particleCanvas" class="particle-canvas"></canvas>

      <!-- Ambient glow orbs -->
      <div class="glow-orb orb-1"></div>
      <div class="glow-orb orb-2"></div>

      <!-- Brand content -->
      <div class="showcase-content">
        <div class="showcase-logo">
          <div class="logo-hex">
            <svg width="72" height="72" viewBox="0 0 72 72" fill="none">
              <path d="M36 4L66 20V52L36 68L6 52V20L36 4Z" stroke="#C5A55A" stroke-width="1.5" fill="none" />
              <path
                d="M36 16L54 26V46L36 56L18 46V26L36 16Z"
                stroke="#D4AF37"
                stroke-width="1"
                fill="none"
                opacity="0.5"
              />
              <path d="M36 28L44 33V43L36 48L28 43V33L36 28Z" fill="#C5A55A" opacity="0.8" />
            </svg>
            <div class="logo-ring"></div>
          </div>
        </div>
        <h1 class="showcase-title">TradingAgents</h1>
        <p class="showcase-subtitle">多智能体股票分析学习平台</p>
        <div class="showcase-divider"></div>
        <div class="showcase-features">
          <div class="feature-line">
            <span class="feature-dot"></span>
            <span>12 智能体协作分析引擎</span>
          </div>
          <div class="feature-line">
            <span class="feature-dot"></span>
            <span>实时市场数据监控</span>
          </div>
          <div class="feature-line">
            <span class="feature-dot"></span>
            <span>AI 驱动深度投资洞察</span>
          </div>
        </div>
      </div>

      <div class="showcase-footer">
        <p>&copy; 2025 TradingAgents-CN. All rights reserved.</p>
      </div>
    </div>

    <!-- Right Form Panel -->
    <div class="login-form-side">
      <div class="login-card">
        <div class="card-noise"></div>
        <div class="card-border-glow"></div>
        <div class="card-header">
          <h2>欢迎回来</h2>
          <p>登录您的账户以继续</p>
        </div>

        <el-form
          :model="loginForm"
          :rules="loginRules"
          ref="loginFormRef"
          label-position="top"
          size="large"
          class="login-form"
        >
          <el-form-item label="用户名" prop="username">
            <el-input
              v-model="loginForm.username"
              placeholder="请输入用户名"
              prefix-icon="User"
            />
          </el-form-item>

          <el-form-item label="密码" prop="password">
            <el-input
              v-model="loginForm.password"
              type="password"
              placeholder="请输入密码"
              prefix-icon="Lock"
              show-password
              @keyup.enter="handleLogin"
            />
          </el-form-item>

          <el-form-item>
            <div class="form-options">
              <el-checkbox v-model="loginForm.rememberMe">记住我</el-checkbox>
            </div>
          </el-form-item>

          <el-form-item>
            <el-button
              type="primary"
              size="large"
              class="login-btn"
              :loading="loginLoading"
              @click="handleLogin"
            >
              <span class="btn-text">登 录</span>
            </el-button>
          </el-form-item>

          <el-form-item>
            <div class="login-tip">
              <el-text v-if="isDev" size="small" class="dev-hint">
                开发环境默认账号：admin / admin123
              </el-text>
            </div>
          </el-form-item>
        </el-form>

        <div class="card-footer">
          <p class="disclaimer">
            TradingAgents-CN 是一个 AI 多 Agents 的股票分析学习平台。平台中的分析结论、观点均由 AI
            自动生成，仅用于学习与研究，不构成任何投资建议。市场有风险，入市需谨慎。
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const isDev = import.meta.env.DEV

const loginFormRef = ref()
const loginLoading = ref(false)
const particleCanvas = ref<HTMLCanvasElement>()

const loginForm = reactive({
  username: '',
  password: '',
  rememberMe: false
})

const loginRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度不能少于6位', trigger: 'blur' }
  ]
}

// --- Enhanced Particle System with Constellation Lines ---
interface Particle {
  x: number
  y: number
  radius: number
  opacity: number
  speed: number
  angle: number
  angleSpeed: number
}

interface ShootingStar {
  x: number
  y: number
  length: number
  speed: number
  angle: number
  opacity: number
  life: number
}

let animationFrameId = 0
let resizeHandler: (() => void) | null = null

const initParticles = () => {
  const canvas = particleCanvas.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const parent = canvas.parentElement!
  const dpr = window.devicePixelRatio || 1

  const resize = () => {
    const w = parent.clientWidth
    const h = parent.clientHeight
    canvas.width = w * dpr
    canvas.height = h * dpr
    canvas.style.width = `${w}px`
    canvas.style.height = `${h}px`
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }
  resize()
  resizeHandler = resize
  window.addEventListener('resize', resize)

  const w = () => parent.clientWidth
  const h = () => parent.clientHeight

  const particleCount = 45
  const connectionDistance = 120
  const particles: Particle[] = Array.from({ length: particleCount }, () => ({
    x: Math.random() * w(),
    y: Math.random() * h(),
    radius: Math.random() * 1.6 + 0.4,
    opacity: Math.random() * 0.45 + 0.15,
    speed: Math.random() * 0.35 + 0.12,
    angle: Math.random() * Math.PI * 2,
    angleSpeed: (Math.random() - 0.5) * 0.015
  }))

  const shootingStars: ShootingStar[] = []

  const maybeSpawnStar = () => {
    if (shootingStars.length < 2 && Math.random() < 0.002) {
      shootingStars.push({
        x: Math.random() * w() * 0.6,
        y: Math.random() * h() * 0.3,
        length: Math.random() * 60 + 40,
        speed: Math.random() * 4 + 3,
        angle: Math.PI / 6 + Math.random() * (Math.PI / 6),
        opacity: 1,
        life: 1
      })
    }
  }

  const animate = () => {
    ctx.clearRect(0, 0, w(), h())

    // Update & draw particles
    for (const p of particles) {
      p.y -= p.speed
      p.x += Math.sin(p.angle) * 0.25
      p.angle += p.angleSpeed

      if (p.y < -10) {
        p.y = h() + 10
        p.x = Math.random() * w()
      }
      if (p.x < -10) p.x = w() + 10
      if (p.x > w() + 10) p.x = -10
    }

    // Draw constellation lines between nearby particles
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x
        const dy = particles[i].y - particles[j].y
        const dist = Math.sqrt(dx * dx + dy * dy)
        if (dist < connectionDistance) {
          const lineOpacity = (1 - dist / connectionDistance) * 0.15
          ctx.beginPath()
          ctx.moveTo(particles[i].x, particles[i].y)
          ctx.lineTo(particles[j].x, particles[j].y)
          ctx.strokeStyle = `rgba(197, 165, 90, ${lineOpacity})`
          ctx.lineWidth = 0.5
          ctx.stroke()
        }
      }
    }

    // Draw particle dots
    for (const p of particles) {
      ctx.beginPath()
      ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(197, 165, 90, ${p.opacity})`
      ctx.fill()
    }

    // Shooting stars
    maybeSpawnStar()
    for (let i = shootingStars.length - 1; i >= 0; i--) {
      const s = shootingStars[i]
      s.x += Math.cos(s.angle) * s.speed
      s.y += Math.sin(s.angle) * s.speed
      s.life -= 0.012
      s.opacity = Math.max(0, s.life)

      if (s.life <= 0) {
        shootingStars.splice(i, 1)
        continue
      }

      const tailX = s.x - Math.cos(s.angle) * s.length * s.opacity
      const tailY = s.y - Math.sin(s.angle) * s.length * s.opacity
      const gradient = ctx.createLinearGradient(tailX, tailY, s.x, s.y)
      gradient.addColorStop(0, `rgba(197, 165, 90, 0)`)
      gradient.addColorStop(1, `rgba(232, 212, 139, ${s.opacity * 0.8})`)

      ctx.beginPath()
      ctx.moveTo(tailX, tailY)
      ctx.lineTo(s.x, s.y)
      ctx.strokeStyle = gradient
      ctx.lineWidth = 1.5
      ctx.stroke()

      ctx.beginPath()
      ctx.arc(s.x, s.y, 2, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(247, 231, 206, ${s.opacity})`
      ctx.fill()
    }

    animationFrameId = requestAnimationFrame(animate)
  }
  animate()
}

const cleanupParticles = () => {
  if (resizeHandler) {
    window.removeEventListener('resize', resizeHandler)
    resizeHandler = null
  }
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId)
    animationFrameId = 0
  }
}

// --- Login logic ---
const handleLogin = async () => {
  if (loginLoading.value) return

  try {
    await loginFormRef.value.validate()
    loginLoading.value = true

    const success = await authStore.login({
      username: loginForm.username,
      password: loginForm.password
    })

    if (success) {
      ElMessage.success('登录成功')
      const redirectPath = authStore.getAndClearRedirectPath()
      router.push(redirectPath)
    } else {
      ElMessage.error('用户名或密码错误')
    }
  } catch (error) {
    if ((error as Error).message && !(error as Error).message.includes('validate')) {
      ElMessage.error('登录失败，请重试')
    }
  } finally {
    loginLoading.value = false
  }
}

onMounted(() => {
  initParticles()
})

onUnmounted(() => {
  cleanupParticles()
})
</script>

<style lang="scss" scoped>
/* ==================== Layout ==================== */
.login-page {
  display: flex;
  min-height: 100vh;
  overflow: hidden;
}

/* ==================== Left Showcase Panel ==================== */
.login-showcase {
  flex: 0 0 55%;
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: flex-start;
  padding: 60px;
  background: $login-dark-bg;
  color: $login-bg-cream;
  overflow: hidden;
}

/* ==================== Aurora Background Effect ==================== */
.aurora {
  position: absolute;
  border-radius: 50%;
  opacity: 0.5;
  filter: blur(80px);
  pointer-events: none;
  will-change: transform, opacity;
}

.aurora-1 {
  width: 60vmax;
  height: 60vmax;
  top: -20%;
  left: -10%;
  background: radial-gradient(circle, rgba(197, 165, 90, 0.35) 0%, rgba(212, 175, 55, 0.1) 40%, transparent 70%);
  animation: aurora-drift-1 18s ease-in-out infinite, aurora-hue 30s linear infinite;
}

.aurora-2 {
  width: 50vmax;
  height: 50vmax;
  bottom: -15%;
  right: -15%;
  background: radial-gradient(circle, rgba(247, 231, 206, 0.3) 0%, rgba(183, 110, 121, 0.15) 40%, transparent 70%);
  animation: aurora-drift-2 22s ease-in-out infinite, aurora-hue 35s linear infinite reverse;
}

.aurora-3 {
  width: 40vmax;
  height: 40vmax;
  top: 30%;
  left: 20%;
  background: radial-gradient(circle, rgba(232, 212, 139, 0.2) 0%, rgba(197, 165, 90, 0.05) 50%, transparent 70%);
  animation: aurora-drift-3 25s ease-in-out infinite, aurora-hue 40s linear infinite;
}

/* ==================== Noise Texture Overlay ==================== */
.noise-overlay {
  position: absolute;
  inset: 0;
  z-index: 0;
  opacity: 0.03;
  pointer-events: none;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='1'/%3E%3C/svg%3E");
  background-repeat: repeat;
  background-size: 256px 256px;
}

/* ==================== Scan Line Effect ==================== */
.scan-line {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  background: linear-gradient(
    to bottom,
    transparent 0%,
    rgba(197, 165, 90, 0.03) 50%,
    transparent 100%
  );
  background-size: 100% 4px;
  animation: scan-sweep 6s ease-in-out infinite;
  mask-image: linear-gradient(to bottom, transparent 0%, black 50%, transparent 100%);
  -webkit-mask-image: linear-gradient(to bottom, transparent 0%, black 50%, transparent 100%);
}

/* ==================== Particle Canvas ==================== */
.particle-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 2;
  pointer-events: none;
}

/* ==================== Glow Orbs ==================== */
.glow-orb {
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
  z-index: 1;
  will-change: transform, opacity;
}

.orb-1 {
  width: 250px;
  height: 250px;
  top: 8%;
  left: -3%;
  background: radial-gradient(circle, rgba(197, 165, 90, 0.15) 0%, transparent 70%);
  animation: float-orb 8s ease-in-out infinite;
}

.orb-2 {
  width: 180px;
  height: 180px;
  bottom: 12%;
  right: 8%;
  background: radial-gradient(circle, rgba(183, 110, 121, 0.1) 0%, transparent 70%);
  animation: float-orb 11s ease-in-out infinite 3s;
}

/* ==================== Showcase Content ==================== */
.showcase-content {
  position: relative;
  z-index: 3;
  animation: content-fade-in 1s ease-out 0.2s both;
}

.showcase-logo {
  margin-bottom: 32px;
}

.logo-hex {
  position: relative;
  width: 72px;
  height: 72px;

  svg {
    position: relative;
    z-index: 1;
    filter: drop-shadow(0 0 16px rgba(197, 165, 90, 0.4));
  }
}

.logo-ring {
  position: absolute;
  inset: -14px;
  border: 1px solid rgba(197, 165, 90, 0.2);
  border-radius: 50%;
  animation: logo-ring-rotate 25s linear infinite;

  &::after {
    content: '';
    position: absolute;
    top: -3px;
    left: 50%;
    width: 6px;
    height: 6px;
    background: $login-gold-glow;
    border-radius: 50%;
    box-shadow: 0 0 10px rgba(212, 175, 55, 0.7);
  }
}

.showcase-title {
  font-size: 48px;
  font-weight: 700;
  letter-spacing: 0.02em;
  margin: 0 0 8px;
  background: linear-gradient(135deg, $login-bg-cream 20%, $login-gold-champagne 60%, $login-gold-bright 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  text-shadow: none;
  filter: drop-shadow(0 0 30px rgba(197, 165, 90, 0.25));
}

.showcase-subtitle {
  font-size: 17px;
  font-weight: 400;
  color: rgba(197, 165, 90, 0.85);
  margin: 0 0 36px;
  letter-spacing: 0.06em;
  text-shadow: 0 0 20px rgba(197, 165, 90, 0.15);
}

.showcase-divider {
  width: 48px;
  height: 2px;
  background: linear-gradient(90deg, $login-gold-primary, transparent);
  margin-bottom: 28px;
  box-shadow: 0 0 12px rgba(197, 165, 90, 0.3);
}

.showcase-features {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.feature-line {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
  color: rgba(255, 254, 249, 0.6);
  letter-spacing: 0.02em;
}

.feature-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: $login-gold-primary;
  box-shadow: 0 0 8px rgba(197, 165, 90, 0.5);
  flex-shrink: 0;
}

.showcase-footer {
  position: absolute;
  bottom: 24px;
  left: 60px;
  z-index: 3;

  p {
    margin: 0;
    font-size: 12px;
    color: rgba(255, 254, 249, 0.25);
  }
}

/* ==================== Right Form Panel ==================== */
.login-form-side {
  flex: 0 0 45%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(180deg, $login-bg-cream 0%, $login-bg-pearl 100%);
  padding: 40px;
  position: relative;
}

/* ==================== Glass Card 2.0 ==================== */
.login-card {
  position: relative;
  width: 100%;
  max-width: 420px;
  background: $login-glass-bg;
  backdrop-filter: blur(40px) saturate(1.6);
  -webkit-backdrop-filter: blur(40px) saturate(1.6);
  border: 1px solid $login-glass-border;
  border-radius: 24px;
  padding: 48px 40px;
  box-shadow:
    0 4px 6px rgba(0, 0, 0, 0.02),
    0 12px 40px rgba(0, 0, 0, 0.05),
    0 0 0 1px rgba(255, 255, 255, 0.6) inset,
    0 0 100px rgba(197, 165, 90, 0.04);
  animation: card-enter 0.8s cubic-bezier(0.16, 1, 0.3, 1) forwards;
  overflow: hidden;
}

/* Card noise texture for glassmorphism 2.0 */
.card-noise {
  position: absolute;
  inset: 0;
  z-index: 0;
  opacity: 0.02;
  border-radius: 24px;
  pointer-events: none;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='1'/%3E%3C/svg%3E");
  background-repeat: repeat;
  background-size: 256px 256px;
}

/* Rotating border glow */
.card-border-glow {
  position: absolute;
  inset: -2px;
  z-index: 0;
  border-radius: 26px;
  background: conic-gradient(
    from 0deg,
    transparent 0%,
    rgba(197, 165, 90, 0.45) 6%,
    transparent 14%,
    transparent 50%,
    rgba(212, 175, 55, 0.25) 56%,
    transparent 64%
  );
  animation: rotate-border-glow 10s linear infinite;
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask-composite: exclude;
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  padding: 1.5px;
  pointer-events: none;
}

/* ==================== Card Header ==================== */
.card-header {
  margin-bottom: 32px;
  position: relative;
  z-index: 1;

  h2 {
    font-size: 26px;
    font-weight: 600;
    color: $login-text-primary;
    margin: 0 0 6px;
    letter-spacing: -0.01em;
  }

  p {
    font-size: 14px;
    color: $login-text-secondary;
    margin: 0;
  }
}

/* ==================== Form Overrides ==================== */
.login-form {
  position: relative;
  z-index: 1;

  :deep(.el-form-item__label) {
    color: $login-text-secondary;
    font-size: 13px;
    font-weight: 500;
    letter-spacing: 0.04em;
    padding-bottom: 4px;
  }

  :deep(.el-input__wrapper) {
    background: $login-input-bg;
    border-radius: 12px 12px 4px 4px;
    box-shadow: none;
    border-bottom: 2px solid rgba(197, 165, 90, 0.2);
    transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
    padding: 6px 14px;

    &:hover {
      border-bottom-color: rgba(197, 165, 90, 0.45);
      background: rgba(255, 254, 249, 0.7);
    }
  }

  :deep(.el-input.is-focus .el-input__wrapper) {
    border-bottom-color: $login-gold-primary;
    box-shadow: 0 4px 24px rgba(197, 165, 90, 0.12);
    background: rgba(255, 254, 249, 0.8);
  }

  :deep(.el-input__prefix .el-icon) {
    color: $login-gold-muted;
    transition: color 0.3s ease;
  }

  :deep(.el-input.is-focus .el-input__prefix .el-icon) {
    color: $login-gold-primary;
  }

  :deep(.el-input__inner) {
    color: $login-text-primary;

    &::placeholder {
      color: $login-text-muted;
    }
  }
}

.form-options {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;

  :deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
    background-color: $login-gold-primary;
    border-color: $login-gold-primary;
  }

  :deep(.el-checkbox__input.is-checked + .el-checkbox__label) {
    color: $login-gold-dark;
  }

  :deep(.el-checkbox__inner) {
    transition: all 0.2s ease;
    border-radius: 4px;

    &:hover {
      border-color: $login-gold-primary;
    }
  }
}

/* ==================== Login Button ==================== */
.login-btn {
  width: 100% !important;
  height: 50px !important;
  background: linear-gradient(
    135deg,
    $login-gold-dark 0%,
    $login-gold-primary 30%,
    $login-gold-glow 60%,
    $login-gold-bright 100%
  ) !important;
  background-size: 200% 200% !important;
  border: none !important;
  border-radius: 12px !important;
  color: $login-text-primary !important;
  font-weight: 600 !important;
  letter-spacing: 0.12em !important;
  font-size: 15px !important;
  position: relative;
  overflow: hidden;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);

  &::before {
    content: '';
    position: absolute;
    top: 0;
    left: -100%;
    width: 100%;
    height: 100%;
    background: linear-gradient(
      90deg,
      transparent,
      rgba(255, 255, 255, 0.2),
      transparent
    );
    animation: shimmer 3.5s ease-in-out infinite;
    pointer-events: none;
  }

  &:hover {
    transform: translateY(-2px);
    background-position: 100% 0 !important;
    box-shadow:
      0 8px 32px rgba(197, 165, 90, 0.35),
      0 0 60px rgba(197, 165, 90, 0.1) !important;
  }

  &:active {
    transform: translateY(0);
  }
}

.btn-text {
  position: relative;
  z-index: 1;
}

/* ==================== Dev Hint ==================== */
.login-tip {
  text-align: center;
  width: 100%;

  .dev-hint {
    color: $login-gold-muted !important;
    opacity: 0.8;
  }
}

/* ==================== Card Footer ==================== */
.card-footer {
  position: relative;
  z-index: 1;
  margin-top: 16px;

  .disclaimer {
    margin: 0;
    font-size: 11px;
    line-height: 1.7;
    color: $login-text-muted;
    text-align: center;
  }
}

/* ==================== Keyframes ==================== */
@keyframes aurora-drift-1 {
  0%,
  100% {
    transform: translate(0, 0) scale(1);
  }
  25% {
    transform: translate(10vw, 8vh) scale(1.1);
  }
  50% {
    transform: translate(5vw, -5vh) scale(0.95);
  }
  75% {
    transform: translate(-5vw, 5vh) scale(1.05);
  }
}

@keyframes aurora-drift-2 {
  0%,
  100% {
    transform: translate(0, 0) scale(1);
  }
  25% {
    transform: translate(-8vw, -6vh) scale(1.05);
  }
  50% {
    transform: translate(-3vw, 8vh) scale(1.1);
  }
  75% {
    transform: translate(6vw, -3vh) scale(0.95);
  }
}

@keyframes aurora-drift-3 {
  0%,
  100% {
    transform: translate(0, 0) scale(1);
  }
  33% {
    transform: translate(8vw, 6vh) scale(1.08);
  }
  66% {
    transform: translate(-6vw, -4vh) scale(0.92);
  }
}

@keyframes aurora-hue {
  0% {
    filter: blur(80px) hue-rotate(0deg);
  }
  100% {
    filter: blur(80px) hue-rotate(360deg);
  }
}

@keyframes scan-sweep {
  0% {
    transform: translateY(-100%);
  }
  100% {
    transform: translateY(100%);
  }
}

@keyframes float-orb {
  0%,
  100% {
    transform: translateY(0) scale(1);
    opacity: 0.3;
  }
  50% {
    transform: translateY(-25px) scale(1.08);
    opacity: 0.5;
  }
}

@keyframes rotate-border-glow {
  0% {
    transform: rotate(0deg);
  }
  100% {
    transform: rotate(360deg);
  }
}

@keyframes shimmer {
  0% {
    left: -100%;
  }
  100% {
    left: 100%;
  }
}

@keyframes card-enter {
  from {
    opacity: 0;
    transform: translateY(40px) scale(0.96);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes content-fade-in {
  from {
    opacity: 0;
    transform: translateY(24px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes logo-ring-rotate {
  0% {
    transform: rotate(0deg);
  }
  100% {
    transform: rotate(360deg);
  }
}

/* ==================== Responsive ==================== */
@media (max-width: 1200px) {
  .login-showcase {
    flex: 0 0 50%;
    padding: 48px;
  }

  .login-form-side {
    flex: 0 0 50%;
  }

  .showcase-title {
    font-size: 40px;
  }
}

@media (max-width: 992px) {
  .login-showcase {
    flex: 0 0 45%;
    padding: 36px;
  }

  .login-form-side {
    flex: 0 0 55%;
  }

  .showcase-title {
    font-size: 34px;
  }

  .showcase-features {
    gap: 10px;
  }
}

@media (max-width: 768px) {
  .login-page {
    flex-direction: column;
  }

  .login-showcase {
    display: none;
  }

  .login-form-side {
    flex: 1;
    background: $login-dark-bg;
    padding: 24px;
  }

  .login-card {
    background: rgba(255, 254, 249, 0.07);
    border-color: rgba(197, 165, 90, 0.18);
    backdrop-filter: blur(24px);
    -webkit-backdrop-filter: blur(24px);
    box-shadow:
      0 8px 32px rgba(0, 0, 0, 0.3),
      0 0 0 1px rgba(255, 255, 255, 0.04) inset;

    .card-header h2 {
      color: $login-bg-cream;
    }

    .card-header p {
      color: rgba(255, 254, 249, 0.5);
    }
  }

  .login-form {
    :deep(.el-form-item__label) {
      color: rgba(255, 254, 249, 0.55);
    }

    :deep(.el-input__wrapper) {
      background: rgba(255, 254, 249, 0.06);
      border-bottom-color: rgba(197, 165, 90, 0.15);
    }

    :deep(.el-input__inner) {
      color: $login-bg-cream;
    }
  }

  .card-footer .disclaimer {
    color: rgba(255, 254, 249, 0.25);
  }
}

@media (max-width: 480px) {
  .login-form-side {
    padding: 16px;
  }

  .login-card {
    padding: 36px 24px;
    border-radius: 18px;
  }

  .card-header h2 {
    font-size: 22px;
  }
}

/* ==================== Reduced Motion ==================== */
@media (prefers-reduced-motion: reduce) {
  .aurora,
  .glow-orb,
  .logo-ring,
  .card-border-glow,
  .scan-line {
    animation: none !important;
  }

  .login-card {
    animation: none !important;
    opacity: 1;
    transform: none;
  }

  .showcase-content {
    animation: none !important;
    opacity: 1;
    transform: none;
  }

  .login-btn::before {
    animation: none !important;
  }
}
</style>
