<script setup lang="ts">
/**
 * Interactive 3D hero: a faceted knowledge core with a wireframe shell, orbiting satellites and a
 * particle field. three.js is imported lazily so the initial bundle stays unchanged, and the whole
 * scene degrades to a static panel when WebGL is missing or the user prefers reduced motion.
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Material as ThreeMaterial } from 'three'
import { t } from '../i18n'
import {
  PARTICLE_COUNT, clamp, cssColor, currentTheme, damp, pixelRatio,
  prefersReducedMotion, rotationFromDrag, supportsWebGL, zoomFromWheel,
} from '../three/sceneKit'

type Three = typeof import('three')

const props = defineProps<{ active?: boolean }>()
const host = ref<HTMLElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
const state = ref<'loading' | 'ready' | 'static' | 'unsupported'>('loading')
const rotation = ref('0.00,0.00')
const pulseTarget = ref(0)

let teardown: (() => void) | null = null

function buildScene(THREE: Three) {
  const element = canvas.value!
  const renderer = new THREE.WebGLRenderer({ canvas: element, antialias: true, alpha: true, powerPreference: 'low-power' })
  renderer.setPixelRatio(pixelRatio(window.devicePixelRatio))
  renderer.setClearColor(0x000000, 0)

  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100)
  camera.position.set(0, 0.35, 6.5)

  const group = new THREE.Group()
  scene.add(group)

  const accentBase = new THREE.Color(cssColor('--accent', '#147b75'))

  const coreMaterial = new THREE.MeshStandardMaterial({
    color: new THREE.Color(cssColor('--accent', '#147b75')), flatShading: true,
    emissive: new THREE.Color(cssColor('--accent', '#147b75')), emissiveIntensity: 0.12,
    roughness: 0.38, metalness: 0.22, transparent: true, opacity: 0.95,
  })
  const core = new THREE.Mesh(new THREE.IcosahedronGeometry(1.22, 1), coreMaterial)

  const shellMaterial = new THREE.MeshBasicMaterial({
    color: new THREE.Color(cssColor('--accent', '#147b75')), wireframe: true, transparent: true, opacity: 0.2,
  })
  const shell = new THREE.Mesh(new THREE.IcosahedronGeometry(1.66, 1), shellMaterial)

  const ringMaterial = new THREE.MeshBasicMaterial({
    color: new THREE.Color(cssColor('--accent', '#147b75')), transparent: true, opacity: 0.42,
  })
  const ring = new THREE.Mesh(new THREE.TorusGeometry(2.12, 0.016, 8, 160), ringMaterial)
  ring.rotation.set(Math.PI / 2.3, 0, 0.12)

  // Soft additive glow behind the core: a radial-gradient sprite keeps the "lit from within" look.
  const glowCanvas = document.createElement('canvas')
  glowCanvas.width = glowCanvas.height = 256
  const glowContext = glowCanvas.getContext('2d')
  if (glowContext) {
    const gradient = glowContext.createRadialGradient(128, 128, 0, 128, 128, 128)
    gradient.addColorStop(0, 'rgba(255,255,255,0.9)')
    gradient.addColorStop(0.32, 'rgba(255,255,255,0.3)')
    gradient.addColorStop(1, 'rgba(255,255,255,0)')
    glowContext.fillStyle = gradient
    glowContext.fillRect(0, 0, 256, 256)
  }
  const glowTexture = new THREE.CanvasTexture(glowCanvas)
  const glowMaterial = new THREE.SpriteMaterial({
    map: glowTexture, color: new THREE.Color(cssColor('--accent', '#147b75')), transparent: true,
    opacity: 0.34, depthWrite: false, blending: THREE.AdditiveBlending,
  })
  const glow = new THREE.Sprite(glowMaterial)
  glow.scale.setScalar(6.2)

  const satellites = [0, 1, 2].map(index => {
    const material = new THREE.MeshStandardMaterial({
      color: new THREE.Color(cssColor('--accent', '#147b75')), roughness: 0.3, metalness: 0.1,
      emissive: new THREE.Color(cssColor('--accent', '#147b75')), emissiveIntensity: 0.4,
    })
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.082, 18, 18), material)
    mesh.userData.phase = (index / 3) * Math.PI * 2
    return mesh
  })

  const positions = new Float32Array(PARTICLE_COUNT * 3)
  for (let index = 0; index < PARTICLE_COUNT; index += 1) {
    const radius = 2.5 + Math.random() * 2.2
    const theta = Math.random() * Math.PI * 2
    const phi = Math.acos(2 * Math.random() - 1)
    positions[index * 3] = radius * Math.sin(phi) * Math.cos(theta)
    positions[index * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta) * 0.7
    positions[index * 3 + 2] = radius * Math.cos(phi)
  }
  const particleGeometry = new THREE.BufferGeometry()
  particleGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  const particleMaterial = new THREE.PointsMaterial({
    color: new THREE.Color(cssColor('--accent', '#147b75')), size: 0.05, transparent: true,
    opacity: 0.55, depthWrite: false, sizeAttenuation: true,
  })
  const particles = new THREE.Points(particleGeometry, particleMaterial)

  group.add(core, shell, ring, glow, particles, ...satellites)
  // Children inherit the group rotation for dragging, but the shell keeps a slow independent spin.
  const ambient = new THREE.AmbientLight(0xffffff, 0.75)
  const key = new THREE.DirectionalLight(0xffffff, 1.25)
  key.position.set(2.6, 3.2, 2.6)
  const rim = new THREE.DirectionalLight(new THREE.Color(cssColor('--accent', '#147b75')), 0.95)
  rim.position.set(-3.1, -1.7, -2.3)
  scene.add(ambient, key, rim)

  const applyTheme = () => {
    const dark = currentTheme() === 'dark'
    // In light mode the raw accent reads as a very dark ball, so lift it towards white.
    const surface = accentBase.clone().lerp(new THREE.Color('#ffffff'), dark ? 0.04 : 0.26)
    coreMaterial.color.copy(surface)
    coreMaterial.emissive.copy(accentBase)
    ;(coreMaterial.emissiveIntensity as number) = dark ? 0.16 : 0.1
    shellMaterial.color.copy(accentBase)
    ringMaterial.color.copy(accentBase)
    glowMaterial.color.copy(accentBase)
    particleMaterial.color.copy(accentBase)
    ambient.intensity = dark ? 0.5 : 0.82
    key.intensity = dark ? 1.1 : 1.35
    rim.intensity = dark ? 1.05 : 0.95
    coreMaterial.opacity = dark ? 0.92 : 0.96
    shellMaterial.opacity = dark ? 0.26 : 0.2
    ringMaterial.opacity = dark ? 0.5 : 0.42
    glowMaterial.opacity = dark ? 0.45 : 0.28
    particleMaterial.opacity = dark ? 0.62 : 0.5
  }
  applyTheme()

  const target = { x: 0.18, y: -0.4, zoom: 6.5 }
  const current = { x: 0.18, y: -0.4, zoom: 6.5 }
  let dragging = false
  let pointerId = -1
  let lastX = 0
  let lastY = 0
  let pulse = 0
  const start = performance.now()

  const onPointerDown = (event: PointerEvent) => {
    dragging = true
    pointerId = event.pointerId
    lastX = event.clientX
    lastY = event.clientY
    element.setPointerCapture(event.pointerId)
    element.classList.add('is-dragging')
  }
  const onPointerMove = (event: PointerEvent) => {
    if (!dragging || event.pointerId !== pointerId) return
    const [dx, dy] = rotationFromDrag(event.clientX - lastX, event.clientY - lastY)
    lastX = event.clientX
    lastY = event.clientY
    target.y += dx
    target.x = clamp(target.x + dy, -1.1, 1.1)
  }
  const onPointerUp = (event: PointerEvent) => {
    if (event.pointerId !== pointerId) return
    dragging = false
    element.classList.remove('is-dragging')
    if (element.hasPointerCapture(event.pointerId)) element.releasePointerCapture(event.pointerId)
  }
  const onWheel = (event: WheelEvent) => {
    event.preventDefault()
    target.zoom = zoomFromWheel(target.zoom, event.deltaY * 1000)
  }
  element.addEventListener('pointerdown', onPointerDown)
  element.addEventListener('pointermove', onPointerMove)
  element.addEventListener('pointerup', onPointerUp)
  element.addEventListener('pointercancel', onPointerUp)
  element.addEventListener('wheel', onWheel, { passive: false })

  const resize = () => {
    const width = Math.max(host.value?.clientWidth ?? 0, 1)
    const height = Math.max(host.value?.clientHeight ?? 0, 1)
    renderer.setSize(width, height, false)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
  }
  const observer = new ResizeObserver(resize)
  if (host.value) observer.observe(host.value)
  resize()

  const themeObserver = new MutationObserver(applyTheme)
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'style'] })

  let frame = 0
  let lastRotationStamp = 0
  let running = true
  const render = () => {
    if (!running) return
    frame = requestAnimationFrame(render)
    const time = (performance.now() - start) / 1000

    target.y += dragging ? 0 : 0.0022
    current.x = damp(current.x, target.x)
    current.y = damp(current.y, target.y)
    current.zoom = damp(current.zoom, target.zoom, 0.12)
    pulse = damp(pulse, pulseTarget.value, 0.06)

    group.rotation.set(current.x, current.y, 0)
    shell.rotation.y = time * 0.22
    shell.rotation.x = Math.sin(time * 0.3) * 0.12
    ring.rotation.z = 0.12 + time * 0.16
    const breathe = 1 + Math.sin(time * 1.35) * 0.018 + pulse * 0.05
    core.scale.setScalar(breathe)
    coreMaterial.emissiveIntensity = 0.1 + pulse * 0.5
    satellites.forEach(mesh => {
      const angle = (mesh.userData.phase as number) + time * (0.5 + pulse * 0.9)
      mesh.position.set(Math.cos(angle) * 2.08, Math.sin(angle) * 2.08 * Math.sin(ring.rotation.x), Math.sin(angle) * 2.08 * Math.cos(ring.rotation.x))
      mesh.scale.setScalar(1 + pulse * 0.35)
    })
    particles.rotation.y = -time * 0.045
    camera.position.z = current.zoom
    camera.lookAt(0, 0, 0)
    renderer.render(scene, camera)

    if (time - lastRotationStamp > 0.12) {
      lastRotationStamp = time
      rotation.value = `${current.x.toFixed(2)},${current.y.toFixed(2)}`
    }
  }
  render()

  const onVisibility = () => {
    if (document.hidden) {
      running = false
      cancelAnimationFrame(frame)
    } else if (!running) {
      running = true
      render()
    }
  }
  document.addEventListener('visibilitychange', onVisibility)

  return () => {
    running = false
    cancelAnimationFrame(frame)
    document.removeEventListener('visibilitychange', onVisibility)
    observer.disconnect()
    themeObserver.disconnect()
    element.removeEventListener('pointerdown', onPointerDown)
    element.removeEventListener('pointermove', onPointerMove)
    element.removeEventListener('pointerup', onPointerUp)
    element.removeEventListener('pointercancel', onPointerUp)
    element.removeEventListener('wheel', onWheel)
    scene.traverse(object => {
      const mesh = object as {
        geometry?: { dispose?: () => void }
        material?: ThreeMaterial | ThreeMaterial[]
      }
      mesh.geometry?.dispose?.()
      const material = mesh.material
      if (Array.isArray(material)) material.forEach(entry => entry.dispose())
      else material?.dispose?.()
    })
    glowTexture.dispose()
    renderer.dispose()
  }
}

onMounted(async () => {
  if (!supportsWebGL() || prefersReducedMotion()) {
    state.value = 'static'
    return
  }
  // First paint shows the lightweight fallback; the renderer loads once the app is idle, so the
  // interface is never blocked by the 190 kB (gzip) three.js chunk.
  await new Promise<void>(resolve => {
    const timer = window.setTimeout(resolve, 500)
    if (typeof window.requestIdleCallback === 'function') {
      window.requestIdleCallback(() => { window.clearTimeout(timer); resolve() }, { timeout: 900 })
    }
  })
  try {
    const THREE = await import('three')
    if (!canvas.value) return
    teardown = buildScene(THREE)
    state.value = 'ready'
  } catch (error) {
    console.warn('3D scene unavailable:', error)
    state.value = 'unsupported'
  }
})

watch(() => props.active, value => {
  pulseTarget.value = value ? 1 : 0
})

onBeforeUnmount(() => teardown?.())
</script>

<template>
  <div
    ref="host"
    class="hero-scene"
    :data-scene="state"
    :data-rotation="rotation"
    :data-active="active ? '1' : '0'"
    role="img"
    :aria-label="t('chat.hero.hint')"
  >
    <canvas ref="canvas" class="hero-canvas" aria-hidden="true" />
    <div v-if="state !== 'ready'" class="hero-fallback" aria-hidden="true"><span /></div>
    <p v-if="state === 'ready'" class="hero-hint">{{ t('chat.hero.hint') }}</p>
  </div>
</template>
