import React from 'react'
import PropTypes from 'prop-types'
import { Link } from 'react-router-dom'

const Category = ({name, url}) => (
  <li className='category'>
    <Link to={{pathname: url}}>
      <section>
        <header>
          <h3 className='category-header'>{name}</h3>
        </header>
        <div className='category-info'>
          <div className='completed-subcategories'>
            <div className='subcat-progress'>
              5/7
            </div>
            <div className='subcat-text'>Subcategories</div>
          </div>
          <div className='completed-challenges'>
            <div className='challenges-progress'>
              511/700
            </div>
            <div className='status-text'>Completed</div>
          </div>
        </div>
      </section>
    </Link>
  </li>
)

Category.propTypes = {
  name: PropTypes.string,
  url: PropTypes.string
}

export default Category
