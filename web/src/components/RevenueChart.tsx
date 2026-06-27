"use client";

import dynamic from "next/dynamic";
import type { ApexOptions } from "apexcharts";

const Chart = dynamic(() => import("react-apexcharts"), { ssr: false });

export function RevenueChart({ series }: { series: { date: string; revenue: number }[] }) {
  const options: ApexOptions = {
    chart: { toolbar: { show: false }, sparkline: { enabled: true } },
    stroke: { curve: "smooth", width: 2.5, colors: ["#A5B4FC"] },
    fill: {
      type: "gradient",
      gradient: { shadeIntensity: 1, opacityFrom: 0.35, opacityTo: 0, stops: [0, 100] },
      colors: ["#A5B4FC"],
    },
    tooltip: {
      theme: "dark",
      x: { show: false },
      y: { formatter: (v: number) => `$${v.toLocaleString()}` },
    },
    grid: { show: false },
    xaxis: { categories: series.map((s) => s.date.slice(5)) },
  };

  return (
    <Chart
      options={options}
      series={[{ name: "Revenue", data: series.map((s) => s.revenue) }]}
      type="area"
      height={64}
    />
  );
}
