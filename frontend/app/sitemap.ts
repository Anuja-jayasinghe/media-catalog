import type { MetadataRoute } from "next";

const site = "https://mtgl.anujajay.com";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: site, changeFrequency: "weekly", priority: 1 },
    { url: `${site}/?view=movie`, changeFrequency: "weekly", priority: 0.8 },
    { url: `${site}/?view=tv`, changeFrequency: "weekly", priority: 0.8 },
    { url: `${site}/?view=game`, changeFrequency: "weekly", priority: 0.8 },
  ];
}
