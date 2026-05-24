<template>
  <div class="about-page">
    <HeroSection />
    <FeatureGrid />
    <TechStackSection />
    <ProjectInfoSection />
    <ContactFooter />
  </div>
</template>

<script setup lang="ts">
import HeroSection from './components/HeroSection.vue'
import FeatureGrid from './components/FeatureGrid.vue'
import TechStackSection from './components/TechStackSection.vue'
import ProjectInfoSection from './components/ProjectInfoSection.vue'
import ContactFooter from './components/ContactFooter.vue'
</script>

<style lang="scss" scoped>
.about-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px;
}

@media (max-width: 480px) {
  .about-page {
    padding: 0 16px;
  }
}
</style>
