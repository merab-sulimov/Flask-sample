
### Sooo, designer workflow.... :::::
The whole workflow has `4 pages`, and there is 1 endpoint for each page/form.  
## Notes
1. All pages require auth.
2. At least 1 image is needed for each step (1,2,3) for the form to validate. 
3. You can `POST` on each page and will return fields with errors.
4. All requesta are with 
5. All fields are required except `address_line_2` on `step3`.
6. You can see endpoints/data/fields here if you use Advanced-Rest-Client: https://github.com/scaltro/jobdone-backend/pull/1#issuecomment-361545616
7. Each step will accept `POST` form-data and when completed returns the serialized `verification` object json.
## 1
You `GET` to endpoint below which will return the template for frontend rendering.

`/verification` 
## 2
You post to this page only with `country_code`.
`/verification/step/0`
## 3
You POST with fields like in design doc.

`/verification/step/1`
## 4
The previous page has returned the `random_code` for printing. Only validation is document upload. You post here just for image validation.

`/verification/step/2`
## 5
You POST like the page in the design. 

`/verification/step/3`
After doing this and returning success, it will have `state=PENDING` and show up in admin panel.
## Uploading for pages 1,2,3
Page 1,2,3 also have img/pdf uploading. These can all be done by `POST` to endpoint below using normal `multipart/form-data` content-type and sending `body` params `step=1/2/3` (from which page we're uploading) and `photo` for the file. Photo needs to be less than 10MB and image/pdf.

`/api/verification/image_upload/` 
### Getting images for current page
You can also get the images for each step/page with `GET` here: `/verification/images/<int:step>/`
