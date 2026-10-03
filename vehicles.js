//Vehicle cargo capacity and speed, from Eco's AutoGen vehicle sources. Regenerate with: python tools/build_catalog.py
//Modular vehicles (trucks, tractors) get storage from fitted modules: slots/maxWeightKg are null, set them in the page.
window.VEHICLES = {
 "EgyptianCanoe": {
  "slots": 3,
  "maxWeightKg": 400.0,
  "speed": 10.0,
  "water": true,
  "roadMult": 1.0
 },
 "IndustrialBarge": {
  "slots": 96,
  "maxWeightKg": 32000.0,
  "speed": 10.0,
  "water": true,
  "roadMult": 2.0
 },
 "LargeCanoe": {
  "slots": 12,
  "maxWeightKg": 2100.0,
  "speed": 10.0,
  "water": true,
  "roadMult": 1.0
 },
 "MediumFishingTrawler": {
  "slots": 8,
  "maxWeightKg": 1400.0,
  "speed": 10.0,
  "water": true,
  "roadMult": 2.0
 },
 "NorseCanoe": {
  "slots": 12,
  "maxWeightKg": 2100.0,
  "speed": 10.0,
  "water": true,
  "roadMult": 1.0
 },
 "OnFoot": {
  "slots": null,
  "maxWeightKg": null,
  "speed": 5.0,
  "water": false,
  "roadMult": 0.0
 },
 "PoweredCart": {
  "slots": 18,
  "maxWeightKg": 3500.0,
  "speed": 12.0,
  "water": false,
  "roadMult": 1.5
 },
 "Scorpion": {
  "slots": 7,
  "maxWeightKg": 7000.0,
  "speed": 14.0,
  "water": false,
  "roadMult": 1.5,
  "storages": [
   {
    "Accepts": {
     "OnlyTags": [
      "Wood"
     ]
    }
   }
  ]
 },
 "SmallCanoe": {
  "slots": 3,
  "maxWeightKg": 400.0,
  "speed": 10.0,
  "water": true,
  "roadMult": 1.0
 },
 "SmallWoodCart": {
  "slots": 8,
  "maxWeightKg": 1400.0,
  "speed": 10.0,
  "water": false,
  "roadMult": 1.0
 },
 "SmallWoodenBoat": {
  "slots": 18,
  "maxWeightKg": 3500.0,
  "speed": 12.0,
  "water": true,
  "roadMult": 1.0
 },
 "SteamTruck": {
  "slots": null,
  "maxWeightKg": null,
  "speed": 18.0,
  "water": false,
  "roadMult": 3.0
 },
 "TrailerTruck": {
  "slots": 36,
  "maxWeightKg": 8000.0,
  "speed": 20.0,
  "water": false,
  "roadMult": 3.0
 },
 "Truck": {
  "slots": null,
  "maxWeightKg": null,
  "speed": 20.0,
  "water": false,
  "roadMult": 4.0
 },
 "Wheelbarrow": {
  "slots": 8,
  "maxWeightKg": 1400.0,
  "speed": 10.0,
  "water": false,
  "roadMult": 1.0
 },
 "WoodCart": {
  "slots": 12,
  "maxWeightKg": 2100.0,
  "speed": 12.0,
  "water": false,
  "roadMult": 1.0
 },
 "WoodShopCart": {
  "slots": 12,
  "maxWeightKg": 2100.0,
  "speed": 10.0,
  "water": false,
  "roadMult": 1.0
 },
 "WoodenBarge": {
  "slots": 48,
  "maxWeightKg": 10000.0,
  "speed": 10.0,
  "water": true,
  "roadMult": 2.0
 },
 "WoodenTransportShip": {
  "slots": 48,
  "maxWeightKg": 14000.0,
  "speed": 10.0,
  "water": true,
  "roadMult": 2.0
 }
};
