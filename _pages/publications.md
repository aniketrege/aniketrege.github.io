---
layout: page
permalink: /publications/
title: publications
description:
years: [2025, 2023, 2022, 2021, 2020, 2018]
nav: true
nav_order: 1
---
<div style="text-align: right"> <small>*equal contribution</small> </div>
<!-- _pages/publications.md -->
<div class="publications">

{%- for y in page.years %}
  <h2 class="year">{{y}}</h2>
  {% bibliography -f papers -q @*[year={{y}}]* %}
{% endfor %}

</div>
